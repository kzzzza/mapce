from __future__ import annotations

import asyncio
import json
import threading

import pytest

from mapce.application import JobManager, ToolDispatcher


@pytest.mark.asyncio
async def test_write_jobs_run_serially(monkeypatch):
    active = 0
    peak = 0

    async def fake_index_paper(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return json.dumps({"status": "ok", "source": kwargs["source"]})

    monkeypatch.setitem(
        __import__("mapce.mcp.tools", fromlist=["HANDLERS"]).HANDLERS,
        "index_paper",
        fake_index_paper,
    )
    manager = JobManager(ToolDispatcher())
    await manager.start()
    first = await manager.submit("index_paper", {"source": "one"})
    second = await manager.submit("index_paper", {"source": "two"})
    await manager.stop()

    assert peak == 1
    assert manager.get(first.job_id).state == "complete"
    assert manager.get(second.job_id).state == "complete"


@pytest.mark.asyncio
async def test_queued_job_can_be_cancelled(monkeypatch):
    release = threading.Event()

    async def slow_index(**kwargs):
        await asyncio.to_thread(release.wait)
        return json.dumps({"status": "ok"})

    monkeypatch.setitem(
        __import__("mapce.mcp.tools", fromlist=["HANDLERS"]).HANDLERS,
        "index_paper",
        slow_index,
    )
    manager = JobManager(ToolDispatcher())
    await manager.start()
    running = await manager.submit("index_paper", {"source": "one"})
    queued = await manager.submit("index_paper", {"source": "two"})
    await asyncio.sleep(0)
    cancelled = manager.cancel(queued.job_id)
    release.set()
    await manager.stop()

    assert manager.get(running.job_id).state == "complete"
    assert cancelled.state == "cancelled"
