"""Paper/code indexing and repository review page."""

from __future__ import annotations

import asyncio
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Select, Static

from mapce.client import ServiceClientError
from mapce.paper_sources import detect_paper_source

from .common import ConfirmScreen


class IndexPane(Vertical):
    def __init__(self) -> None:
        super().__init__()
        self.paper_id: str | None = None
        self.repositories: dict[str, dict[str, Any]] = {}
        self.selected_repo_url: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("索引与仓库审核", classes="page-title")
        with Vertical(classes="form-box"):
            yield Static("添加论文", classes="section-title")
            with Horizontal(classes="form-row"):
                yield Input(placeholder="arXiv ID、本地 PDF 路径或 URL", id="index-paper-source")
                yield Select(
                    [("arXiv", "arxiv"), ("本地 PDF", "local"), ("URL", "url")],
                    value="arxiv",
                    allow_blank=False,
                    id="index-paper-type",
                )
                yield Select(
                    [("English", "en"), ("中文", "ch")],
                    value="en",
                    allow_blank=False,
                    id="index-paper-language",
                )
                yield Button("提交论文索引", id="index-paper-submit", variant="primary")
        with Vertical(classes="form-box"):
            yield Static("添加代码仓库", classes="section-title")
            with Horizontal(classes="form-row"):
                yield Input(placeholder="Paper ID", id="index-code-paper")
                yield Input(placeholder="https://github.com/owner/repo", id="index-code-url")
                yield Button("提交代码索引", id="index-code-submit", variant="primary")
        with Vertical(classes="form-box"):
            yield Static("仓库关联审核", classes="section-title")
            with Horizontal(classes="form-row"):
                yield Input(placeholder="内部论文 ID 或 arXiv 编号", id="repo-paper-identifier")
                yield Button("载入关联", id="repo-load")
            yield DataTable(id="repo-table", cursor_type="row")
            with Horizontal(classes="toolbar"):
                yield Button("批准并索引", id="repo-approve", variant="primary", disabled=True)
                yield Button("忽略候选", id="repo-ignore", variant="warning", disabled=True)
                yield Button("设为主仓库", id="repo-primary", disabled=True)
                yield Button("删除代码索引", id="repo-delete", variant="error", disabled=True)
        yield Static("", id="index-message", classes="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#repo-table", DataTable)
        table.add_columns("主仓库", "状态", "可信度", "来源", "仓库")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "index-paper-source":
            return
        detected = detect_paper_source(event.value)
        if detected is not None:
            self.query_one("#index-paper-type", Select).value = detected.source_type

    def _set_actions(self, enabled: bool) -> None:
        for selector in ("#repo-approve", "#repo-ignore", "#repo-primary", "#repo-delete"):
            self.query_one(selector, Button).disabled = not enabled

    def _render_repositories(self, rows: list[dict[str, Any]]) -> None:
        self.repositories = {str(row.get("repo_url")): row for row in rows if row.get("repo_url")}
        self.selected_repo_url = None
        self._set_actions(False)
        table = self.query_one("#repo-table", DataTable)
        table.clear()
        for row in rows:
            url = str(row.get("repo_url", ""))
            table.add_row(
                "●" if row.get("is_primary") else "",
                str(row.get("status", "")),
                f"{row.get('confidence', '')} / {row.get('score', '')}",
                str(row.get("source", "")),
                url,
                key=url,
            )

    @work(exclusive=True, group="index-submit")
    async def submit_paper(self) -> None:
        source = self.query_one("#index-paper-source", Input).value.strip()
        message = self.query_one("#index-message", Static)
        button = self.query_one("#index-paper-submit", Button)
        button.disabled = True
        try:
            if not source:
                message.update("请输入论文来源。")
                return
            detected = detect_paper_source(source)
            normalized_source = detected.normalized_source if detected is not None else source
            arguments = {
                "source": normalized_source,
                "source_type": str(self.query_one("#index-paper-type", Select).value),
                "language": str(self.query_one("#index-paper-language", Select).value),
            }
            payload = await asyncio.to_thread(self.app.api.submit_job, "index_paper", arguments)
            message.update(f"论文索引任务已提交：{payload.get('job', {}).get('job_id')}")
        except ServiceClientError as exc:
            message.update(f"提交失败 [{exc.error_code}]：{exc}")
        finally:
            button.disabled = False

    @work(exclusive=True, group="index-submit")
    async def submit_code(self) -> None:
        paper_id = self.query_one("#index-code-paper", Input).value.strip()
        repo_url = self.query_one("#index-code-url", Input).value.strip()
        message = self.query_one("#index-message", Static)
        if not paper_id or not repo_url:
            message.update("Paper ID 和仓库 URL 都不能为空。")
            return
        try:
            payload = await asyncio.to_thread(
                self.app.api.submit_job,
                "index_code",
                {"paper_id": paper_id, "repo_url": repo_url},
            )
            message.update(f"代码索引任务已提交：{payload.get('job', {}).get('job_id')}")
        except ServiceClientError as exc:
            message.update(f"提交失败 [{exc.error_code}]：{exc}")

    @work(exclusive=True, group="repo-load")
    async def load_repositories(self) -> None:
        identifier = self.query_one("#repo-paper-identifier", Input).value.strip()
        message = self.query_one("#index-message", Static)
        if not identifier:
            message.update("请输入论文 ID 或 arXiv 编号。")
            return
        try:
            resolved = await asyncio.to_thread(
                self.app.api.call_tool, "resolve_paper", {"identifier": identifier}
            )
            if resolved.get("status") == "error":
                message.update(f"载入失败 [{resolved.get('error_code')}]：{resolved.get('message')}")
                return
            self.paper_id = resolved["paper_id"]
            overview = await asyncio.to_thread(
                self.app.api.call_tool,
                "get_paper_overview",
                {"paper_id": self.paper_id},
            )
        except ServiceClientError as exc:
            message.update(f"载入失败 [{exc.error_code}]：{exc}")
            return
        rows = overview.get("code_repositories", [])
        self._render_repositories(rows)
        message.update(f"{resolved.get('title')}：{len(rows)} 个仓库关联，代码状态 {overview.get('code_status')}。")

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "repo-table":
            return
        self.selected_repo_url = str(event.row_key.value)
        self._set_actions(True)
        row = self.repositories.get(self.selected_repo_url, {})
        self.query_one("#index-message", Static).update(
            f"已选择 {self.selected_repo_url}；证据：{row.get('evidence') or '—'}"
        )

    @work(exclusive=True, group="repo-action")
    async def submit_repo_action(self, action: str) -> None:
        if not self.paper_id or not self.selected_repo_url:
            return
        message = self.query_one("#index-message", Static)
        if action == "approve":
            tool = "index_code"
            arguments = {"paper_id": self.paper_id, "repo_url": self.selected_repo_url}
        else:
            tool = "review_code_repository"
            arguments = {
                "paper_id": self.paper_id,
                "repo_url": self.selected_repo_url,
                "action": action,
            }
        try:
            payload = await asyncio.to_thread(self.app.api.submit_job, tool, arguments)
            message.update(f"仓库任务已提交：{payload.get('job', {}).get('job_id')}")
        except ServiceClientError as exc:
            message.update(f"提交失败 [{exc.error_code}]：{exc}")

    @work(exclusive=True, group="repo-delete")
    async def delete_repository(self) -> None:
        if not self.paper_id or not self.selected_repo_url:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmScreen(
                "删除代码索引",
                f"将删除 {self.selected_repo_url} 在论文 {self.paper_id} 下的代码 chunk、方法映射和仓库关联。",
            )
        )
        if not confirmed:
            return
        try:
            payload = await asyncio.to_thread(
                self.app.api.submit_job,
                "delete_code_repository",
                {"paper_id": self.paper_id, "repo_url": self.selected_repo_url},
            )
            self.query_one("#index-message", Static).update(
                f"删除任务已提交：{payload.get('job', {}).get('job_id')}"
            )
        except ServiceClientError as exc:
            self.query_one("#index-message", Static).update(f"提交失败：{exc}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "index-paper-submit":
                if event.button.disabled:
                    return
                event.button.disabled = True
                self.submit_paper()
            case "index-code-submit":
                self.submit_code()
            case "repo-load":
                self.load_repositories()
            case "repo-approve":
                self.submit_repo_action("approve")
            case "repo-ignore":
                self.submit_repo_action("ignore")
            case "repo-primary":
                self.submit_repo_action("set_primary")
            case "repo-delete":
                self.delete_repository()
