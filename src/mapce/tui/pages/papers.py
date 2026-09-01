"""Paper inventory, exact arXiv lookup, semantic search, and deletion."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from typing import Any

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Select, Static

from mapce.client import ServiceClientError

from .common import ConfirmScreen


class PapersPane(Vertical):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self.rows_by_id: dict[str, dict[str, Any]] = {}
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
            yield Select(
                [
                    ("发表年份 · 最新", "year_desc"),
                    ("发表年份 · 最早", "year_asc"),
                    ("入库时间 · 最新", "indexed_desc"),
                    ("入库时间 · 最早", "indexed_asc"),
                    ("标题 · A–Z", "title_asc"),
                    ("标题 · Z–A", "title_desc"),
                    ("Paper ID · 升序", "id_asc"),
                    ("Paper ID · 降序", "id_desc"),
                    ("Chunk 数量 · 多到少", "chunks_desc"),
                    ("Chunk 数量 · 少到多", "chunks_asc"),
                    ("代码状态", "code_status_asc"),
                ],
                value="year_desc",
                allow_blank=False,
                id="paper-sort",
            )
        with Horizontal(classes="split"):
            with Vertical(classes="split-left"):
                yield DataTable(id="papers-table", cursor_type="row")
            with Vertical(classes="split-right"):
                with VerticalScroll(id="paper-detail-scroll"):
                    yield Static("选择一篇论文查看摘要、章节目录、图表和仓库状态。", id="paper-detail")
                yield Button("删除论文", id="paper-delete", variant="error", disabled=True)
        yield Static("", id="papers-message", classes="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.add_columns("序号", "Paper ID", "标题", "年份", "论文状态", "代码状态")

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
        self.rows = self._sort_rows(rows)
        self.rows_by_id = {str(row.get("paper_id")): row for row in rows if row.get("paper_id")}
        self._render_rows()

    @staticmethod
    def _indexed_timestamp(value: Any) -> float | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return None

    def _sort_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sort_name = str(self.query_one("#paper-sort", Select).value or "year_desc")
        field, direction = sort_name.rsplit("_", 1)
        reverse = direction == "desc"

        def primary(row: dict[str, Any]) -> Any:
            if field == "year":
                value = row.get("year")
                return int(value) if value is not None else None
            if field == "indexed":
                return self._indexed_timestamp(row.get("indexed_at"))
            if field == "title":
                return str(row.get("title") or "").casefold()
            if field == "id":
                return str(row.get("paper_id") or "").casefold()
            if field == "chunks":
                value = row.get("chunk_count")
                return int(value) if value is not None else None
            return str(row.get("code_status") or "").casefold()

        tie_sorted = sorted(
            rows,
            key=lambda row: (
                str(row.get("title") or "").casefold(),
                str(row.get("paper_id") or "").casefold(),
            ),
        )
        known = [row for row in tie_sorted if primary(row) is not None]
        missing = [row for row in tie_sorted if primary(row) is None]
        return sorted(known, key=primary, reverse=reverse) + missing

    def _render_rows(self) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.clear()
        for number, row in enumerate(self.rows, start=1):
            paper_id = str(row.get("paper_id", ""))
            table.add_row(
                str(number),
                paper_id,
                str(row.get("title", ""))[:80],
                str(row.get("year") or "—"),
                str(row.get("status") or row.get("paper_status") or ""),
                str(row.get("code_status") or ""),
                key=paper_id,
            )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "paper-sort" and self.is_mounted:
            self.rows = self._sort_rows(self.rows)
            self._render_rows()

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
        citation = overview.get("citation") or {}
        citation_missing = ", ".join(citation.get("missing_fields") or []) or "无"
        citation_text = escape(str(citation.get("plain_text") or "—"))
        citation_url = escape(str(citation.get("url") or "—"))
        citation_key = escape(str(citation.get("citation_key") or "—"))
        bibtex = escape(str(citation.get("bibtex") or "—"))
        csl_json = escape(json.dumps(citation.get("csl_json") or {}, ensure_ascii=False, indent=2))
        detail.update(
            f"[b]{escape(str(overview.get('title', '')))}[/b]\n"
            f"ID: {escape(paper_id)}\nArXiv: {escape(str(overview.get('arxiv_id') or '—'))}\n"
            f"作者: {authors}\n年份/Venue: {escape(str(overview.get('year') or '—'))} / "
            f"{escape(str(overview.get('venue') or '—'))}\n"
            f"代码状态: {escape(str(overview.get('code_status') or ''))}\n\n"
            f"[b]引用信息[/b]\n"
            f"DOI: {escape(str(citation.get('doi') or '—'))}\n"
            f"URL: {citation_url}\nCitation Key: {citation_key}\n"
            f"核验状态: {escape(str(citation.get('verification_status') or '—'))}\n"
            f"缺失字段: {escape(citation_missing)}\n"
            f"标准文本: {citation_text}\n\n"
            f"[b]BibTeX[/b]\n{bibtex}\n\n"
            f"[b]CSL-JSON[/b]\n{csl_json}\n\n"
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
            case "paper-delete":
                self.delete_selected()
