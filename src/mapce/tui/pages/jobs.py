"""Serialized background job viewer."""

from __future__ import annotations

import asyncio
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from mapce.client import ServiceClientError


class JobsPane(Vertical):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.selected_job_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("后台任务", classes="page-title")
        with Horizontal(classes="toolbar"):
            yield Button("刷新", id="jobs-refresh", variant="primary")
            yield Button("取消排队任务", id="jobs-cancel", variant="warning", disabled=True)
            yield Button("重试失败任务", id="jobs-retry", disabled=True)
        yield DataTable(id="jobs-table", cursor_type="row")
        yield Static("", id="jobs-message", classes="status-line")

    def on_mount(self) -> None:
        self.query_one("#jobs-table", DataTable).add_columns(
            "Job ID", "操作", "状态", "创建时间", "耗时/错误"
        )

    @work(exclusive=True, group="jobs")
    async def refresh_jobs(self) -> None:
        message = self.query_one("#jobs-message", Static)
        message.update("正在读取任务队列…")
        try:
            payload = await asyncio.to_thread(self.app.api.list_jobs)
        except ServiceClientError as exc:
            message.update(f"读取失败 [{exc.error_code}]：{exc}")
            return
        rows = payload.get("jobs", [])
        self.jobs = {str(job.get("job_id")): job for job in rows}
        table = self.query_one("#jobs-table", DataTable)
        table.clear()
        for job in rows:
            job_id = str(job.get("job_id", ""))
            detail = job.get("error") or ""
            if job.get("started_at") and job.get("finished_at"):
                detail = "已结束"
            table.add_row(
                job_id[:12],
                str(job.get("tool", "")),
                str(job.get("state", "")),
                str(job.get("created_at", ""))[:19],
                str(detail)[:80],
                key=job_id,
            )
        message.update(f"共 {len(rows)} 个队列与历史任务。")

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "jobs-table":
            return
        self.selected_job_id = str(event.row_key.value)
        job = self.jobs.get(self.selected_job_id, {})
        state = job.get("state")
        self.query_one("#jobs-cancel", Button).disabled = state != "queued"
        self.query_one("#jobs-retry", Button).disabled = state != "failed"
        self.query_one("#jobs-message", Static).update(
            f"{job.get('tool')} · {state} · {job.get('error') or '无错误'}"
        )

    @work(exclusive=True, group="job-action")
    async def cancel_selected(self) -> None:
        if not self.selected_job_id:
            return
        try:
            payload = await asyncio.to_thread(self.app.api.cancel_job, self.selected_job_id)
            self.query_one("#jobs-message", Static).update(
                f"任务状态：{payload.get('job', {}).get('state')}"
            )
        except ServiceClientError as exc:
            self.query_one("#jobs-message", Static).update(f"取消失败：{exc}")
        self.refresh_jobs()

    @work(exclusive=True, group="job-action")
    async def retry_selected(self) -> None:
        job = self.jobs.get(self.selected_job_id or "")
        if not job or job.get("state") != "failed":
            return
        try:
            payload = await asyncio.to_thread(
                self.app.api.submit_job,
                str(job.get("tool")),
                dict(job.get("arguments") or {}),
            )
            self.query_one("#jobs-message", Static).update(
                f"重试任务已提交：{payload.get('job', {}).get('job_id')}"
            )
        except ServiceClientError as exc:
            self.query_one("#jobs-message", Static).update(f"重试失败：{exc}")
        self.refresh_jobs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "jobs-refresh":
                self.refresh_jobs()
            case "jobs-cancel":
                self.cancel_selected()
            case "jobs-retry":
                self.retry_selected()
