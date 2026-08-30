"""Dashboard page."""

from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from mapce.client import ServiceClientError

from .common import human_bytes


class DashboardPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("数据库总览", classes="page-title")
        with Grid(classes="card-grid"):
            yield Static("服务\n等待连接", id="service-card", classes="card")
            yield Static("论文\n—", id="papers-card", classes="card")
            yield Static("存储\n—", id="storage-card", classes="card")
        with Horizontal(classes="toolbar"):
            yield Button("刷新", id="dashboard-refresh", variant="primary")
        yield DataTable(id="dashboard-status")
        yield Static("", id="dashboard-message", classes="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#dashboard-status", DataTable)
        table.add_columns("项目", "状态", "详情")

    @work(exclusive=True, group="dashboard")
    async def refresh_data(self) -> None:
        message = self.query_one("#dashboard-message", Static)
        message.update("正在读取后台状态…")
        try:
            service = await asyncio.to_thread(self.app.api.service_status)
            stats = await asyncio.to_thread(self.app.api.call_tool, "get_stats", {})
            doctor = await asyncio.to_thread(self.app.api.doctor)
        except ServiceClientError as exc:
            message.update(f"连接失败 [{exc.error_code}]：{exc}")
            return

        self.query_one("#service-card", Static).update(
            f"服务  PID {service.get('pid')}\n"
            f"RSS {human_bytes(service.get('rss_bytes'))}\n"
            f"模型 {'已加载' if service.get('embedding_loaded') else '按需加载'}"
        )
        self.query_one("#papers-card", Static).update(
            f"论文  {stats.get('total_papers', 0)}\n"
            f"论文块 {stats.get('paper_chunks', 0)}\n"
            f"代码块 {stats.get('code_chunks', 0)}"
        )
        self.query_one("#storage-card", Static).update(
            f"存储  {human_bytes(doctor.get('database_size_bytes'))}\n"
            f"文件 {doctor.get('database_file_count', 0)}\n"
            f"可用内存 {human_bytes(service.get('system_available_memory_bytes'))}"
        )
        table = self.query_one("#dashboard-status", DataTable)
        table.clear()
        for status, count in sorted(stats.get("code_status_distribution", {}).items()):
            table.add_row("代码状态", str(status), str(count))
        vector = stats.get("vector_index") or {}
        table.add_row(
            "向量索引",
            "可用" if vector.get("vector_index_present") else "缺失",
            f"rows={vector.get('row_count', 0)}",
        )
        table.add_row(
            "全文索引",
            "可用" if vector.get("fts_index_present") else "缺失",
            "fulltext_search_fts",
        )
        for item in vector.get("indices", []):
            unindexed = int(item.get("num_unindexed_rows") or 0)
            if unindexed:
                table.add_row("未索引行", str(item.get("name", "index")), str(unindexed))
        message.update("后台状态已更新。")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dashboard-refresh":
            self.refresh_data()
