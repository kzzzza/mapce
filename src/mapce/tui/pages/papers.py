"""Paper inventory, exact arXiv lookup, semantic search, and deletion."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Select, Static

from mapce.client import ServiceClientError

from .common import ConfirmScreen


class PapersPane(Vertical):
    PAGE_SIZE = 20

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self.rows_by_id: dict[str, dict[str, Any]] = {}
        self.page = 0
        self.selected_paper_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("论文库", classes="page-title")
        with Horizontal(classes="toolbar"):
            yield Input(placeholder="标题、关键词或 arXiv 编号", id="paper-query")
            yield Button("精确查找", id="paper-exact", variant="primary")
            yield Button("语义检索", id="paper-semantic")
            yield Button("全部论文", id="paper-all")
        with Horizontal(classes="toolbar filters"):
            yield Input(placeholder="最早年份", id="paper-year-min", type="integer")
            yield Input(placeholder="最晚年份", id="paper-year-max", type="integer")
            yield Input(placeholder="Venue", id="paper-venue")
            yield Select(
                [("全部代码状态", ""), ("已索引", "indexed"), ("未发现代码", "no_code"),
                 ("待审核", "needs_review"), ("失败", "failed")],
                value="",
                allow_blank=False,
                id="paper-code-status",
            )
        with Horizontal(classes="split"):
            with Vertical(classes="split-left"):
                yield DataTable(id="papers-table", cursor_type="row")
                with Horizontal(classes="pager"):
                    yield Button("上一页", id="papers-prev")
                    yield Static("第 1 页", id="papers-page")
                    yield Button("下一页", id="papers-next")
            with VerticalScroll(classes="split-right"):
                yield Static("选择一篇论文查看摘要、章节目录、图表和仓库状态。", id="paper-detail")
                yield Button("删除论文", id="paper-delete", variant="error", disabled=True)
        yield Static("", id="papers-message", classes="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.add_columns("Paper ID", "标题", "年份", "论文状态", "代码状态")

    def _filters(self) -> tuple[int | None, int | None, str, str]:
        def integer(selector: str) -> int | None:
            value = self.query_one(selector, Input).value.strip()
            return int(value) if value else None

        return (
            integer("#paper-year-min"),
            integer("#paper-year-max"),
            self.query_one("#paper-venue", Input).value.strip(),
            str(self.query_one("#paper-code-status", Select).value or ""),
        )

    def _apply_local_filters(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        year_min, year_max, venue, code_status = self._filters()
        filtered = []
        for row in rows:
            year = row.get("year")
            if year_min is not None and (year is None or int(year) < year_min):
                continue
            if year_max is not None and (year is None or int(year) > year_max):
                continue
            if venue and venue.casefold() not in str(row.get("venue") or "").casefold():
                continue
            if code_status and row.get("code_status") != code_status:
                continue
            filtered.append(row)
        return filtered

    def _set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.rows_by_id = {str(row.get("paper_id")): row for row in rows if row.get("paper_id")}
        self.page = 0
        self._render_page()

    def _render_page(self) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.clear()
        start = self.page * self.PAGE_SIZE
        page_rows = self.rows[start : start + self.PAGE_SIZE]
        for row in page_rows:
            paper_id = str(row.get("paper_id", ""))
            table.add_row(
                paper_id,
                str(row.get("title", ""))[:80],
                str(row.get("year") or "—"),
                str(row.get("status") or row.get("paper_status") or ""),
                str(row.get("code_status") or ""),
                key=paper_id,
            )
        pages = max(1, (len(self.rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.query_one("#papers-page", Static).update(f"第 {self.page + 1}/{pages} 页 · {len(self.rows)} 篇")
        self.query_one("#papers-prev", Button).disabled = self.page == 0
        self.query_one("#papers-next", Button).disabled = self.page + 1 >= pages

    @work(exclusive=True, group="paper-list")
    async def load_all(self) -> None:
        message = self.query_one("#papers-message", Static)
        message.update("正在读取论文列表…")
        try:
            payload = await asyncio.to_thread(self.app.api.call_tool, "list_indexed_papers", {})
            rows = self._apply_local_filters(payload.get("papers", []))
        except (ServiceClientError, ValueError) as exc:
            message.update(f"读取失败：{exc}")
            return
        self._set_rows(rows)
        message.update(f"已载入 {len(rows)} 篇论文。")

    @work(exclusive=True, group="paper-list")
    async def exact_lookup(self) -> None:
        identifier = self.query_one("#paper-query", Input).value.strip()
        message = self.query_one("#papers-message", Static)
        if not identifier:
            message.update("请输入内部论文 ID 或 arXiv 编号。")
            return
        message.update("正在执行本地精确查找…")
        try:
            resolved = await asyncio.to_thread(
                self.app.api.call_tool, "resolve_paper", {"identifier": identifier}
            )
        except ServiceClientError as exc:
            message.update(f"查找失败 [{exc.error_code}]：{exc}")
            return
        if resolved.get("status") == "error":
            message.update(f"查找失败 [{resolved.get('error_code')}]：{resolved.get('message')}")
            return
        self._set_rows([resolved])
        message.update("已命中本地论文；本次查找未加载嵌入模型。")
        await self._load_detail(resolved["paper_id"])

    @work(exclusive=True, group="paper-list")
    async def semantic_search(self) -> None:
        query = self.query_one("#paper-query", Input).value.strip()
        message = self.query_one("#papers-message", Static)
        if not query:
            message.update("请输入语义查询。")
            return
        year_min, year_max, venue, code_status = self._filters()
        arguments: dict[str, Any] = {"query": query, "top_k": 50}
        if year_min is not None:
            arguments["year_min"] = year_min
        if year_max is not None:
            arguments["year_max"] = year_max
        if venue:
            arguments["venue"] = venue
        message.update("正在进行向量与全文混合检索…")
        try:
            payload = await asyncio.to_thread(self.app.api.call_tool, "search_papers", arguments)
        except ServiceClientError as exc:
            message.update(f"检索失败 [{exc.error_code}]：{exc}")
            return
        rows = payload.get("results", [])
        if code_status:
            try:
                inventory = await asyncio.to_thread(
                    self.app.api.call_tool, "list_indexed_papers", {}
                )
            except ServiceClientError as exc:
                message.update(f"代码状态筛选失败 [{exc.error_code}]：{exc}")
                return
            status_by_id = {
                str(row.get("paper_id")): row.get("code_status")
                for row in inventory.get("papers", [])
            }
            for row in rows:
                row["code_status"] = status_by_id.get(str(row.get("paper_id")))
            rows = [row for row in rows if row.get("code_status") == code_status]
        self._set_rows(rows)
        message.update(f"返回 {len(rows)} 篇不同论文。")

    async def _load_detail(self, paper_id: str) -> None:
        detail = self.query_one("#paper-detail", Static)
        detail.update("正在读取论文概览…")
        try:
            overview = await asyncio.to_thread(
                self.app.api.call_tool, "get_paper_overview", {"paper_id": paper_id}
            )
        except ServiceClientError as exc:
            detail.update(f"读取失败 [{exc.error_code}]：{exc}")
            return
        if overview.get("status") == "error":
            detail.update(f"读取失败：{overview.get('message')}")
            return
        self.selected_paper_id = paper_id
        self.query_one("#paper-delete", Button).disabled = False
        authors = escape(", ".join(overview.get("authors") or []) or "未知")
        sections = "\n".join(
            f"  • {escape(str(row.get('heading') or '(未命名章节)'))}"
            for row in overview.get("sections", [])[:40]
        ) or "  —"
        repos = "\n".join(
            f"  • [{'主' if row.get('is_primary') else '辅'}] "
            f"{escape(str(row.get('status') or ''))}  {escape(str(row.get('repo_url') or ''))}"
            for row in overview.get("code_repositories", [])
        ) or "  未发现仓库"
        abstract = escape(str(overview.get("abstract") or "")[:4000])
        detail.update(
            f"[b]{escape(str(overview.get('title', '')))}[/b]\n"
            f"ID: {escape(paper_id)}\nArXiv: {escape(str(overview.get('arxiv_id') or '—'))}\n"
            f"作者: {authors}\n年份/Venue: {escape(str(overview.get('year') or '—'))} / "
            f"{escape(str(overview.get('venue') or '—'))}\n"
            f"代码状态: {escape(str(overview.get('code_status') or ''))}\n\n"
            f"[b]摘要[/b]\n{abstract}\n\n[b]章节目录[/b]\n{sections}\n\n[b]代码仓库[/b]\n{repos}"
        )

    @work(exclusive=True, group="paper-detail")
    async def load_detail(self, paper_id: str) -> None:
        await self._load_detail(paper_id)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "papers-table":
            return
        paper_id = str(event.row_key.value)
        self.load_detail(paper_id)

    @work(exclusive=True, group="paper-delete")
    async def delete_selected(self) -> None:
        if not self.selected_paper_id:
            return
        paper_id = self.selected_paper_id
        confirmed = await self.app.push_screen_wait(
            ConfirmScreen(
                "删除论文",
                f"将删除论文 {paper_id}、其正文 chunk、代码 chunk、仓库关联和方法映射。此操作将进入后台写队列。",
            )
        )
        if not confirmed:
            return
        try:
            payload = await asyncio.to_thread(
                self.app.api.submit_job, "delete_paper", {"paper_id": paper_id}
            )
            self.query_one("#papers-message", Static).update(
                f"删除任务已提交：{payload.get('job', {}).get('job_id')}"
            )
        except ServiceClientError as exc:
            self.query_one("#papers-message", Static).update(f"提交失败：{exc}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "paper-all":
                self.load_all()
            case "paper-exact":
                self.exact_lookup()
            case "paper-semantic":
                self.semantic_search()
            case "papers-prev":
                self.page = max(0, self.page - 1)
                self._render_page()
            case "papers-next":
                if (self.page + 1) * self.PAGE_SIZE < len(self.rows):
                    self.page += 1
                    self._render_page()
            case "paper-delete":
                self.delete_selected()
