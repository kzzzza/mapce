"""Starlette application for REST and MCP Streamable HTTP transports."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import psutil

from mapce import __version__
from mapce.application import JobManager, ToolDispatcher
from mapce.contracts.service import JobSubmitRequest, ToolCallRequest
from mapce.mcp.backend import create_backend_mcp_server
from mapce.mcp.tools import TOOL_DEFINITIONS

from .runtime import ServiceInfo

logger = logging.getLogger("mapce.service")


class _MCPASGIApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        await self.manager.handle_request(scope, receive, send)


class LocalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin and origin not in {
            f"http://{request.url.hostname}",
            f"http://{request.url.hostname}:{request.url.port}",
            "http://127.0.0.1",
            "http://localhost",
        }:
            return JSONResponse(
                {
                    "status": "error",
                    "error_code": "origin_not_allowed",
                    "message": "Origin is not allowed for the local MAPCE service.",
                },
                status_code=403,
            )

        if request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse(
                {
                    "status": "error",
                    "error_code": "unauthorized",
                    "message": "A valid local service token is required.",
                },
                status_code=401,
            )
        return await call_next(request)


def _embedding_loaded() -> bool:
    module = sys.modules.get("mapce.core.embedding")
    return bool(module is not None and getattr(module, "_model", None) is not None)


def create_app(
    info: ServiceInfo,
    token: str,
    *,
    shutdown_callback: Callable[[], Awaitable[None] | None] | None = None,
    dispatcher: ToolDispatcher | None = None,
) -> Starlette:
    started_monotonic = time.monotonic()
    dispatcher = dispatcher or ToolDispatcher()
    jobs = JobManager(dispatcher)
    mcp_server = create_backend_mcp_server(dispatcher)
    manager = StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=True,
        stateless=False,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{info.host}:{info.port}", f"localhost:{info.port}"],
            allowed_origins=[
                f"http://{info.host}:{info.port}",
                f"http://localhost:{info.port}",
            ],
        ),
    )

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service_id": info.service_id,
                "version": __version__,
                "pid": os.getpid(),
                "data_dir_hash": info.data_dir_hash,
                "uptime_seconds": round(time.monotonic() - started_monotonic, 3),
                "embedding_loaded": _embedding_loaded(),
            }
        )

    async def service_status(_: Request) -> JSONResponse:
        process = psutil.Process()
        return JSONResponse(
            {
                "status": "ok",
                "service_id": info.service_id,
                "pid": os.getpid(),
                "host": info.host,
                "port": info.port,
                "base_url": info.base_url,
                "data_dir_hash": info.data_dir_hash,
                "version": __version__,
                "embedding_loaded": _embedding_loaded(),
                "rss_bytes": process.memory_info().rss,
                "system_available_memory_bytes": psutil.virtual_memory().available,
                "jobs": [job.model_dump(mode="json") for job in jobs.list()],
            }
        )

    async def list_tools(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "tools": [tool.model_dump(mode="json", by_alias=True) for tool in TOOL_DEFINITIONS],
            }
        )

    async def doctor(_: Request) -> JSONResponse:
        def inspect_paths() -> dict[str, Any]:
            data_path = Path(info.data_dir)
            size = 0
            file_count = 0
            if data_path.exists():
                for root, _, files in os.walk(data_path):
                    for filename in files:
                        try:
                            size += (Path(root) / filename).stat().st_size
                            file_count += 1
                        except OSError:
                            continue
            return {
                "data_dir": str(data_path),
                "data_dir_exists": data_path.exists(),
                "database_size_bytes": size,
                "database_file_count": file_count,
                "runtime_dir": str(Path(info.token_file).parent),
                "log_path": str(Path(info.token_file).with_name("service.log")),
            }

        paths = await asyncio.to_thread(inspect_paths)
        return JSONResponse(
            {
                "status": "ok",
                "service_id": info.service_id,
                "version": __version__,
                "host": info.host,
                "port": info.port,
                "embedding_loaded": _embedding_loaded(),
                "warmup_enabled": os.environ.get("MAPCE_WARMUP_EMBEDDING", "0").lower()
                in {"1", "true", "yes", "on"},
                **paths,
            }
        )

    async def service_logs(request: Request) -> JSONResponse:
        try:
            tail = min(max(int(request.query_params.get("tail", "200")), 1), 500)
        except ValueError:
            return JSONResponse(
                {"status": "error", "error_code": "invalid_tail", "message": "tail must be an integer."},
                status_code=400,
            )
        path = Path(info.token_file).with_name("service.log")

        def read_lines() -> list[str]:
            try:
                return path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
            except FileNotFoundError:
                return []

        return JSONResponse(
            {"status": "ok", "path": str(path), "lines": await asyncio.to_thread(read_lines)}
        )

    async def call_tool(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        try:
            payload = ToolCallRequest.model_validate(await request.json())
        except Exception as exc:
            return JSONResponse(
                {"status": "error", "error_code": "invalid_request", "message": str(exc)},
                status_code=400,
            )
        result = await dispatcher.call(name, payload.arguments)
        status_code = 400 if result.get("error_code") in {"unknown_tool", "invalid_arguments"} else 200
        return JSONResponse(result, status_code=status_code)

    async def submit_job(request: Request) -> JSONResponse:
        try:
            payload = JobSubmitRequest.model_validate(await request.json())
            job = await jobs.submit(payload.tool, payload.arguments)
        except ValueError as exc:
            return JSONResponse(
                {"status": "error", "error_code": "invalid_job", "message": str(exc)},
                status_code=400,
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"status": "error", "error_code": "service_shutting_down", "message": str(exc)},
                status_code=503,
            )
        return JSONResponse({"status": "ok", "job": job.model_dump(mode="json")}, status_code=202)

    async def list_jobs(_: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "jobs": [job.model_dump(mode="json") for job in jobs.list()]}
        )

    async def get_job(request: Request) -> JSONResponse:
        job = jobs.get(request.path_params["job_id"])
        if job is None:
            return JSONResponse(
                {"status": "error", "error_code": "job_not_found", "message": "Job not found."},
                status_code=404,
            )
        return JSONResponse({"status": "ok", "job": job.model_dump(mode="json")})

    async def cancel_job(request: Request) -> JSONResponse:
        job = jobs.cancel(request.path_params["job_id"])
        if job is None:
            return JSONResponse(
                {"status": "error", "error_code": "job_not_found", "message": "Job not found."},
                status_code=404,
            )
        return JSONResponse({"status": "ok", "job": job.model_dump(mode="json")})

    async def shutdown(_: Request) -> JSONResponse:
        if shutdown_callback is None:
            return JSONResponse(
                {"status": "error", "error_code": "shutdown_unavailable", "message": "Shutdown is unavailable."},
                status_code=503,
            )
        value = shutdown_callback()
        if value is not None:
            await value
        return JSONResponse({"status": "ok", "message": "Shutdown requested."})

    @asynccontextmanager
    async def lifespan(_: Starlette):
        await jobs.start()
        warmup = os.environ.get("MAPCE_WARMUP_EMBEDDING", "0").lower() in {
            "1", "true", "yes", "on",
        }
        if warmup:
            try:
                from mapce.core.embedding import embed_single

                await asyncio.to_thread(embed_single, "startup warmup")
            except Exception:
                logger.exception("Embedding warmup failed; the model will retry on first use")
        async with manager.run():
            yield
        await jobs.stop()

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/service", service_status, methods=["GET"]),
        Route("/api/tools", list_tools, methods=["GET"]),
        Route("/api/doctor", doctor, methods=["GET"]),
        Route("/api/logs", service_logs, methods=["GET"]),
        Route("/api/tools/{name:str}", call_tool, methods=["POST"]),
        Route("/api/jobs", submit_job, methods=["POST"]),
        Route("/api/jobs", list_jobs, methods=["GET"]),
        Route("/api/jobs/{job_id:str}", get_job, methods=["GET"]),
        Route("/api/jobs/{job_id:str}/cancel", cancel_job, methods=["POST"]),
        Route("/api/admin/shutdown", shutdown, methods=["POST"]),
        Route("/mcp", _MCPASGIApp(manager)),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(LocalAuthMiddleware, token=token)
    app.state.dispatcher = dispatcher
    app.state.jobs = jobs
    return app
