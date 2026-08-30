"""Textual database manager backed exclusively by the MAPCE local service."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from mapce.client import MapceClient

from .pages import DashboardPane, IndexPane, JobsPane, PapersPane, SystemPane
from .theme import APP_CSS


class MapceTUI(App[None]):
    """Local paper-database management interface; it never opens LanceDB directly."""

    TITLE = "MAPCE · 论文数据库管理器"
    SUB_TITLE = "共享后台 · Agent 接口 · 本地管理"
    CSS = APP_CSS
    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("ctrl+r", "refresh_current", "刷新"),
    ]
    MIN_WIDTH = 76
    MIN_HEIGHT = 22

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        client: MapceClient | None = None,
    ) -> None:
        super().__init__()
        self.api = client or MapceClient(data_dir)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "终端窗口过小。请调整到至少 76×22；当前界面已暂停渲染数据表。",
            id="small-screen-warning",
        )
        with TabbedContent(id="main-tabs"):
            with TabPane("总览", id="tab-dashboard"):
                yield DashboardPane()
            with TabPane("论文库", id="tab-papers"):
                yield PapersPane()
            with TabPane("索引", id="tab-index"):
                yield IndexPane()
            with TabPane("任务", id="tab-jobs"):
                yield JobsPane()
            with TabPane("系统", id="tab-system"):
                yield SystemPane()
        yield Footer()

    def on_mount(self) -> None:
        self._apply_size_guard()
        self.query_one(DashboardPane).refresh_data()

    def _apply_size_guard(self) -> None:
        too_small = self.size.width < self.MIN_WIDTH or self.size.height < self.MIN_HEIGHT
        self.query_one("#small-screen-warning", Static).display = too_small
        self.query_one("#main-tabs", TabbedContent).display = not too_small

    def on_resize(self) -> None:
        self._apply_size_guard()

    def _refresh_tab(self, pane_id: str) -> None:
        if pane_id == "tab-dashboard":
            self.query_one(DashboardPane).refresh_data()
        elif pane_id == "tab-papers":
            self.query_one(PapersPane).load_all()
        elif pane_id == "tab-jobs":
            self.query_one(JobsPane).refresh_jobs()
        elif pane_id == "tab-system":
            self.query_one(SystemPane).refresh_data()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._refresh_tab(str(event.pane.id))

    def action_refresh_current(self) -> None:
        active = self.query_one("#main-tabs", TabbedContent).active
        if active:
            self._refresh_tab(str(active))

    def on_unmount(self) -> None:
        self.api.close()
