"""Client for the singleton MAPCE local service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from mapce.service.process import ensure_service
from mapce.service.runtime import ServiceInfo, read_token


class ServiceClientError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class MapceClient:
    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        auto_start: bool = True,
        timeout: float = 120.0,
    ) -> None:
        self.data_dir = data_dir
        self.auto_start = auto_start
        self.timeout = timeout
        self._info: ServiceInfo | None = None
        self._http = httpx.Client(timeout=timeout)

    def connect(self) -> ServiceInfo:
        if self._info is None:
            if not self.auto_start:
                from mapce.service.process import get_service_status

                status = get_service_status(self.data_dir)
                if not status.get("running"):
                    raise ServiceClientError("service_unavailable", "MAPCE service is not running.")
                self._info = status["info"]
            else:
                self._info = ensure_service(self.data_dir)
        return self._info

    def _headers(self) -> dict[str, str]:
        info = self.connect()
        token = read_token(Path(info.token_file))
        return {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        info = self.connect()
        try:
            response = self._http.request(
                method,
                f"{info.base_url}{path}",
                headers=self._headers(),
                json=json,
                params=params,
            )
        except (OSError, httpx.HTTPError) as exc:
            raise ServiceClientError("service_unavailable", str(exc)) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceClientError("invalid_service_response", str(exc)) from exc
        if response.status_code >= 400:
            raise ServiceClientError(
                payload.get("error_code", "service_error"),
                payload.get("message", f"HTTP {response.status_code}"),
            )
        return payload

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/api/tools/{name}", json={"arguments": arguments})

    async def call_tool_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self.call_tool, name, arguments)

    def service_status(self) -> dict[str, Any]:
        return self.request("GET", "/api/service")

    def submit_job(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/jobs", json={"tool": tool, "arguments": arguments})

    def list_jobs(self) -> dict[str, Any]:
        return self.request("GET", "/api/jobs")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/jobs/{job_id}/cancel")

    def doctor(self) -> dict[str, Any]:
        return self.request("GET", "/api/doctor")

    def logs(self, tail: int = 200) -> dict[str, Any]:
        return self.request("GET", "/api/logs", params={"tail": tail})

    def reset_connection(self) -> None:
        self._http.close()
        self._http = httpx.Client(timeout=self.timeout)
        self._info = None

    def restart_service(self) -> ServiceInfo:
        from mapce.service.process import ServiceProcessError, ensure_service, stop_service

        result = stop_service(self.data_dir)
        if result.get("status") == "error":
            raise ServiceClientError(
                result.get("error_code", "restart_failed"),
                result.get("message", "MAPCE service restart failed."),
            )
        self.reset_connection()
        try:
            self._info = ensure_service(self.data_dir)
        except ServiceProcessError as exc:
            raise ServiceClientError(exc.error_code, str(exc)) from exc
        return self._info

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "MapceClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
