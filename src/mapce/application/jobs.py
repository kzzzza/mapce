"""In-process serialized job queue for database mutations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mapce.contracts.service import JobRecord

from .dispatcher import ToolDispatcher, WRITE_TOOLS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, dispatcher: ToolDispatcher, max_history: int = 200) -> None:
        self.dispatcher = dispatcher
        self.max_history = max_history
        self._jobs: dict[str, JobRecord] = {}
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._accepting = True

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="mapce-write-worker")

    async def stop(self) -> None:
        self._accepting = False
        if self._worker is not None:
            await self._queue.join()
            await self._queue.put(None)
            await self._worker
            self._worker = None

    async def submit(self, tool: str, arguments: dict[str, Any]) -> JobRecord:
        if tool not in WRITE_TOOLS:
            raise ValueError(f"Tool is not a queued write operation: {tool}")
        if not self._accepting:
            raise RuntimeError("Service is shutting down")
        self._trim_history()
        job = JobRecord(
            job_id=uuid4().hex,
            tool=tool,
            arguments=arguments,
            state="queued",
            created_at=_now(),
        )
        self._jobs[job.job_id] = job
        await self._queue.put(job.job_id)
        return job

    def _trim_history(self) -> None:
        terminal = {"complete", "failed", "cancelled"}
        while len(self._jobs) >= self.max_history:
            removable = next(
                (job_id for job_id, job in self._jobs.items() if job.state in terminal),
                None,
            )
            if removable is None:
                break
            self._jobs.pop(removable)

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def cancel(self, job_id: str) -> JobRecord | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.state == "queued":
            job.state = "cancelled"
            job.finished_at = _now()
        elif job.state == "running":
            job.state = "cancelling"
        return job

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id is None:
                    return
                job = self._jobs[job_id]
                if job.state == "cancelled":
                    continue
                job.state = "running"
                job.started_at = _now()
                result = await self.dispatcher.call(job.tool, job.arguments)
                job.result = result
                job.finished_at = _now()
                if result.get("status") == "error":
                    job.state = "failed"
                    job.error = result.get("message")
                else:
                    job.state = "complete"
            except Exception as exc:
                if job_id is not None:
                    job = self._jobs[job_id]
                    job.state = "failed"
                    job.error = str(exc)
                    job.finished_at = _now()
            finally:
                self._queue.task_done()
