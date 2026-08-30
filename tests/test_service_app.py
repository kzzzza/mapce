from __future__ import annotations

from datetime import datetime, timezone
import asyncio

import httpx
import pytest

from mapce.application import ToolDispatcher
from mapce.service.app import create_app
from mapce.service.runtime import ServiceInfo


class FakeDispatcher(ToolDispatcher):
    async def call(self, name, arguments):
        if name == "unknown":
            return {"status": "error", "error_code": "unknown_tool", "message": "missing"}
        return {"status": "ok", "name": name, "arguments": arguments}


def _info(tmp_path):
    return ServiceInfo(
        service_id="test-service",
        pid=123,
        host="127.0.0.1",
        port=8765,
        data_dir=str(tmp_path),
        data_dir_hash="abc123",
        version="0.1.0",
        started_at=datetime.now(timezone.utc).isoformat(),
        token_file=str(tmp_path / "token"),
    )


@pytest.mark.asyncio
async def test_health_is_public_but_api_requires_token(tmp_path):
    app = create_app(_info(tmp_path), "secret", dispatcher=FakeDispatcher())
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            health = await client.get("/health")
            denied = await client.get("/api/service")
            allowed = await client.get(
                "/api/service", headers={"Authorization": "Bearer secret"}
            )
            hostile_origin = await client.get(
                "/api/service",
                headers={
                    "Authorization": "Bearer secret",
                    "Origin": "https://example.invalid",
                },
            )

    assert health.status_code == 200
    assert health.json()["embedding_loaded"] is False
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert hostile_origin.status_code == 403


@pytest.mark.asyncio
async def test_tool_api_uses_shared_dispatcher(tmp_path):
    app = create_app(_info(tmp_path), "secret", dispatcher=FakeDispatcher())
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer secret"}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8765",
            headers=headers,
        ) as client:
            response = await client.post(
                "/api/tools/search_papers", json={"arguments": {"query": "FB"}}
            )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "name": "search_papers",
        "arguments": {"query": "FB"},
    }


@pytest.mark.asyncio
async def test_write_job_api_returns_trackable_job(tmp_path):
    app = create_app(_info(tmp_path), "secret", dispatcher=FakeDispatcher())
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer secret"}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8765",
            headers=headers,
        ) as client:
            submitted = await client.post(
                "/api/jobs",
                json={"tool": "index_paper", "arguments": {"source": "paper.pdf"}},
            )
            job_id = submitted.json()["job"]["job_id"]
            for _ in range(20):
                current = await client.get(f"/api/jobs/{job_id}")
                if current.json()["job"]["state"] == "complete":
                    break
                await asyncio.sleep(0)

    assert submitted.status_code == 202
    assert current.json()["job"]["result"]["name"] == "index_paper"


@pytest.mark.asyncio
async def test_diagnostics_and_bounded_logs_use_authenticated_api(tmp_path):
    info = _info(tmp_path)
    log_path = tmp_path / "service.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    app = create_app(info, "secret", dispatcher=FakeDispatcher())
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer secret"}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8765",
            headers=headers,
        ) as client:
            service = await client.get("/api/service")
            doctor = await client.get("/api/doctor")
            logs = await client.get("/api/logs", params={"tail": 2})
            invalid = await client.get("/api/logs", params={"tail": "many"})

    assert service.json()["base_url"] == "http://127.0.0.1:8765"
    assert doctor.json()["data_dir"] == str(tmp_path)
    assert doctor.json()["database_file_count"] >= 1
    assert logs.json()["lines"] == ["two", "three"]
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "invalid_tail"
