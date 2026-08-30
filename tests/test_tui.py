from __future__ import annotations

from dataclasses import dataclass

import pytest
from textual.widgets import Button, DataTable, Static, TabbedContent

from mapce.tui.app import MapceTUI
from mapce.tui.pages import PapersPane


@dataclass
class _FakeInfo:
    pid: int = 99


class FakeClient:
    def __init__(self) -> None:
        self.closed = False
        self.restarts = 0
        self.calls: list[tuple[str, dict]] = []
        self.submitted: list[tuple[str, dict]] = []

    def service_status(self):
        return {
            "pid": 99,
            "rss_bytes": 64 * 1024 * 1024,
            "embedding_loaded": False,
            "system_available_memory_bytes": 8 * 1024**3,
        }

    def doctor(self):
        return {
            "data_dir": "/tmp/mapce-test",
            "database_size_bytes": 2 * 1024**3,
            "database_file_count": 12,
            "version": "test",
        }

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "get_stats":
            return {
                "total_papers": 2,
                "paper_chunks": 20,
                "code_chunks": 3,
                "code_status_distribution": {"no_code": 1, "indexed": 1},
                "vector_index": {
                    "vector_index_present": True,
                    "fts_index_present": True,
                    "indices": [],
                },
            }
        if name == "list_indexed_papers":
            return {
                "papers": [
                    {
                        "paper_id": "paper-one",
                        "title": "Paper One",
                        "year": 2024,
                        "status": "complete",
                        "code_status": "indexed",
                    }
                ]
            }
        if name == "resolve_paper":
            return {
                "status": "ok",
                "paper_id": "paper-one",
                "arxiv_id": "2412.04368",
                "title": "Paper One",
                "paper_status": "complete",
                "code_status": "indexed",
            }
        if name == "get_paper_overview":
            return {
                "status": "ok",
                "paper_id": "paper-one",
                "arxiv_id": "2412.04368",
                "title": "Paper One",
                "authors": ["Ada"],
                "abstract": "Abstract",
                "status": "complete",
                "code_status": "indexed",
                "sections": [{"heading": "1. Method"}],
                "code_repositories": [],
            }
        if name == "search_papers":
            return {
                "results": [
                    {"paper_id": "paper-one", "title": "Paper One", "score": 1.0}
                ]
            }
        return {"status": "ok"}

    def list_jobs(self):
        return {"jobs": []}

    def logs(self, tail=200):
        return {"lines": ["service ready"]}

    def submit_job(self, tool, arguments):
        self.submitted.append((tool, arguments))
        return {"job": {"job_id": "job-one", "tool": tool, "arguments": arguments}}

    def cancel_job(self, job_id):
        return {"job": {"job_id": job_id, "state": "cancelled"}}

    def reset_connection(self):
        return None

    def restart_service(self):
        self.restarts += 1
        return _FakeInfo()

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_tui_renders_dashboard_and_keeps_service_running_on_exit():
    client = FakeClient()
    app = MapceTUI(client=client)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#main-tabs", TabbedContent).active == "tab-dashboard"
        assert "PID 99" in str(app.query_one("#service-card", Static).content)

    assert client.closed is True
    assert client.restarts == 0


@pytest.mark.asyncio
async def test_exact_arxiv_lookup_uses_resolver_without_semantic_search():
    client = FakeClient()
    app = MapceTUI(client=client)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#main-tabs", TabbedContent).active = "tab-papers"
        await pilot.pause()
        await pilot.click("#paper-query")
        await pilot.press(*"2412.04368")
        await pilot.click("#paper-exact")
        await pilot.pause()
        await pilot.pause()

        pane = app.query_one(PapersPane)
        assert pane.rows[0]["paper_id"] == "paper-one"
        assert ("resolve_paper", {"identifier": "2412.04368"}) in client.calls
        assert not any(name == "search_papers" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_small_terminal_displays_warning_instead_of_tables():
    app = MapceTUI(client=FakeClient())
    async with app.run_test(size=(60, 18)) as pilot:
        await pilot.pause()
        assert app.query_one("#small-screen-warning", Static).display is True
        assert app.query_one("#main-tabs", TabbedContent).display is False


@pytest.mark.asyncio
async def test_confirmed_paper_delete_submits_job_from_modal_worker():
    client = FakeClient()
    app = MapceTUI(client=client)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#main-tabs", TabbedContent).active = "tab-papers"
        await pilot.pause()
        await pilot.pause()
        table = app.query_one("#papers-table", DataTable)
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.query_one("#paper-delete", Button).disabled is False

        await pilot.click("#paper-delete")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.click("#confirm")
        await pilot.pause()
        await pilot.pause()

    assert ("delete_paper", {"paper_id": "paper-one"}) in client.submitted


@pytest.mark.asyncio
async def test_system_restart_requires_confirmation():
    client = FakeClient()
    app = MapceTUI(client=client)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#main-tabs", TabbedContent).active = "tab-system"
        await pilot.pause()
        await pilot.click("#system-restart")
        await pilot.pause()
        assert client.restarts == 0
        await pilot.click("#confirm")
        await pilot.pause()
        await pilot.pause()

    assert client.restarts == 1
