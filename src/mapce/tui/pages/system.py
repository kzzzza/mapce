"""Service diagnostics, logs, and controlled restart page."""

from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static

from mapce.client import ServiceClientError

from .common import ConfirmScreen, human_bytes


class SystemPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("系统诊断", classes="page-title")
        with Horizontal(classes="toolbar"):
            yield Button("刷新诊断", id="system-refresh", variant="primary")
            yield Button("读取日志", id="system-read-logs")
            yield Button("重新连接", id="system-reconnect")
            yield Button("重启后台", id="system-restart", variant="warning")
        with VerticalScroll(classes="system-panel"):
            yield Static("等待读取后台诊断。", id="system-output")
        yield Static("后台日志（最近 200 行）", classes="section-title")
        with VerticalScroll(classes="system-log-panel"):
            yield Static("尚未读取日志。", id="system-logs")
        yield Static("", id="system-message", classes="status-line")

    @work(exclusive=True, group="system-status")
    async def refresh_data(self) -> None:
        message = self.query_one("#system-message", Static)
        message.update("正在读取诊断信息…")
        try:
            service = await asyncio.to_thread(self.app.api.service_status)
            doctor = await asyncio.to_thread(self.app.api.doctor)
            stats = await asyncio.to_thread(self.app.api.call_tool, "get_stats", {})
        except ServiceClientError as exc:
            message.update(f"诊断失败 [{exc.error_code}]：{exc}")
            return
        index = stats.get("vector_index") or {}
        lines = [
            f"服务 PID: {service.get('pid')}",
            f"监听地址: {service.get('base_url') or service.get('url') or '—'}",
            f"数据目录: {doctor.get('data_dir') or '—'}",
            f"数据库目录: {doctor.get('database_path') or '—'}",
            f"数据库大小: {human_bytes(doctor.get('database_size_bytes'))}",
            f"服务 RSS: {human_bytes(service.get('rss_bytes'))}",
            f"系统可用内存: {human_bytes(service.get('system_available_memory_bytes'))}",
            f"嵌入模型: {'已加载' if service.get('embedding_loaded') else '未加载（按需）'}",
            f"向量索引: {'可用' if index.get('vector_index_present') else '缺失'}",
            f"全文索引: {'可用' if index.get('fts_index_present') else '缺失'}",
            f"MAPCE 版本: {doctor.get('mapce_version') or doctor.get('version') or '—'}",
        ]
        self.query_one("#system-output", Static).update("\n".join(lines))
        message.update("诊断信息已更新。")

    @work(exclusive=True, group="system-logs")
    async def load_logs(self) -> None:
        message = self.query_one("#system-message", Static)
        message.update("正在读取日志…")
        try:
            payload = await asyncio.to_thread(self.app.api.logs, 200)
        except ServiceClientError as exc:
            message.update(f"日志读取失败 [{exc.error_code}]：{exc}")
            return
        lines = payload.get("lines") or []
        self.query_one("#system-logs", Static).update("\n".join(lines) or "日志为空。")
        message.update(f"已读取 {len(lines)} 行日志。")

    @work(exclusive=True, group="system-reconnect")
    async def reconnect(self) -> None:
        self.app.api.reset_connection()
        self.query_one("#system-message", Static).update("连接缓存已清除，正在重新连接。")
        self.refresh_data()

    @work(exclusive=True, group="system-restart")
    async def restart(self) -> None:
        confirmed = await self.app.push_screen_wait(
            ConfirmScreen(
                "重启 MAPCE 后台",
                "重启会中断当前连接和正在运行的任务。已有轻量 stdio 代理需要在 Agent 会话中重新连接。",
            )
        )
        if not confirmed:
            return
        message = self.query_one("#system-message", Static)
        message.update("正在重启后台服务…")
        try:
            info = await asyncio.to_thread(self.app.api.restart_service)
        except ServiceClientError as exc:
            message.update(f"重启失败 [{exc.error_code}]：{exc}")
            return
        message.update(f"后台已重启，PID {info.pid}。")
        self.refresh_data()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "system-refresh":
                self.refresh_data()
            case "system-read-logs":
                self.load_logs()
            case "system-reconnect":
                self.reconnect()
            case "system-restart":
                self.restart()
