"""Typer command-line entry point and TUI launcher for MAPCE."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from mapce.client import MapceClient, ServiceClientError
from mapce.configuration import (
    ConfigurationError,
    env_file_status,
    load_configured_env,
    set_default_env_file,
    unset_default_env_file,
)
from mapce.service.process import (
    ServiceProcessError,
    ensure_service,
    get_service_status,
    service_logs_path,
    stop_service,
)

app = typer.Typer(
    name="mapce",
    help="Manage and inspect the local MAPCE paper database.",
    no_args_is_help=False,
)
papers_app = typer.Typer(help="Find, inspect, and delete indexed papers.")
search_app = typer.Typer(help="Search papers or content inside one paper.")
index_app = typer.Typer(help="Submit paper and code indexing jobs.")
jobs_app = typer.Typer(help="Inspect and cancel background jobs.")
config_app = typer.Typer(help="Manage persistent MAPCE user configuration.")
app.add_typer(papers_app, name="papers")
app.add_typer(search_app, name="search")
app.add_typer(index_app, name="index")
app.add_typer(jobs_app, name="jobs")
app.add_typer(config_app, name="config")

console = Console()
error_console = Console(stderr=True)


class PaperSourceType(str, Enum):
    local = "local"
    arxiv = "arxiv"
    url = "url"


@dataclass
class CLIState:
    data_dir: Path | None


def _state(ctx: typer.Context) -> CLIState:
    return ctx.find_root().obj


def _client(ctx: typer.Context) -> MapceClient:
    return MapceClient(_state(ctx).data_dir)


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    console.print_json(json.dumps(payload, ensure_ascii=False, default=str))


def _fail(exc: Exception, error_code: str = "command_failed") -> None:
    code = getattr(exc, "error_code", error_code)
    error_console.print_json(
        json.dumps(
            {"status": "error", "error_code": code, "message": str(exc)},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


def _serialize_status(status: dict[str, Any]) -> dict[str, Any]:
    value = dict(status)
    info = value.get("info")
    if info is not None:
        value["info"] = {
            "service_id": info.service_id,
            "pid": info.pid,
            "host": info.host,
            "port": info.port,
            "data_dir": info.data_dir,
            "data_dir_hash": info.data_dir_hash,
            "version": info.version,
            "started_at": info.started_at,
        }
    return value


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override MAPCE_DATA_DIR."),
) -> None:
    """Open the database manager when no subcommand is given."""
    if ctx.invoked_subcommand != "config":
        try:
            load_configured_env(strict=True)
        except ConfigurationError as exc:
            _fail(exc)
    ctx.obj = CLIState(data_dir.expanduser() if data_dir else None)
    if ctx.invoked_subcommand is None:
        from mapce.tui.app import MapceTUI

        MapceTUI(data_dir=ctx.obj.data_dir).run()


@config_app.command("set-env")
def config_set_env(env_file: Path) -> None:
    """Save the default .env path used by every MAPCE entry point."""
    try:
        status = set_default_env_file(env_file)
    except ConfigurationError as exc:
        _fail(exc)
    _emit(
        {
            "status": "ok",
            **status.as_dict(),
            "message": "Default MAPCE env file saved; its values were not copied.",
        },
        True,
    )


@config_app.command("show")
def config_show() -> None:
    """Show the effective env-file path without displaying secret values."""
    try:
        status = env_file_status()
    except ConfigurationError as exc:
        _fail(exc)
    _emit({"status": "ok", **status.as_dict()}, True)


@config_app.command("unset-env")
def config_unset_env() -> None:
    """Remove the saved default .env path."""
    try:
        status = unset_default_env_file()
    except ConfigurationError as exc:
        _fail(exc)
    _emit(
        {
            "status": "ok",
            **status.as_dict(),
            "message": "Saved MAPCE env-file path removed.",
        },
        True,
    )


@app.command("serve")
def serve(ctx: typer.Context) -> None:
    """Start or reuse the background service."""
    try:
        info = ensure_service(_state(ctx).data_dir)
        _emit({"status": "ok", "running": True, "pid": info.pid, "url": info.base_url}, True)
    except ServiceProcessError as exc:
        _fail(exc)


@app.command("serve-status")
def serve_status(ctx: typer.Context) -> None:
    """Show the verified service status."""
    _emit(_serialize_status(get_service_status(_state(ctx).data_dir)), True)


@app.command("serve-kill")
def serve_kill(ctx: typer.Context, force: bool = typer.Option(False, "--force")) -> None:
    """Stop the exact verified service process."""
    result = stop_service(_state(ctx).data_dir, force=force)
    _emit(result, True)
    if result.get("status") == "error":
        raise typer.Exit(1)


@app.command("serve-restart")
def serve_restart(ctx: typer.Context) -> None:
    """Gracefully restart the background service."""
    data_dir = _state(ctx).data_dir
    result = stop_service(data_dir)
    if result.get("status") == "error":
        _emit(result, True)
        raise typer.Exit(1)
    try:
        info = ensure_service(data_dir)
        _emit({"status": "ok", "running": True, "pid": info.pid, "url": info.base_url}, True)
    except ServiceProcessError as exc:
        _fail(exc)


@app.command("serve-logs")
def serve_logs(
    ctx: typer.Context,
    tail: int = typer.Option(0, "--tail", min=0, max=500),
) -> None:
    """Print the log path or the last log lines."""
    path = service_logs_path(_state(ctx).data_dir)
    if tail and path.exists():
        typer.echo("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]))
    else:
        typer.echo(path)


@app.command("stats")
def stats(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Show database and auxiliary-index statistics."""
    client = _client(ctx)
    try:
        _emit(client.call_tool("get_stats", {}), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@app.command("doctor")
def doctor(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Run read-only service and path diagnostics."""
    client = _client(ctx)
    try:
        payload = client.doctor()
        payload["index"] = client.call_tool("get_stats", {})
        _emit(payload, as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@papers_app.command("list")
def papers_list(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """List indexed papers without loading embedding vectors."""
    client = _client(ctx)
    try:
        payload = client.call_tool("list_indexed_papers", {})
        if as_json:
            _emit(payload, True)
        else:
            table = Table("Paper ID", "Title", "Status", "Code")
            for paper in payload.get("papers", []):
                table.add_row(
                    str(paper.get("paper_id", "")),
                    str(paper.get("title", "")),
                    str(paper.get("status", "")),
                    str(paper.get("code_status", "")),
                )
            console.print(table)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@papers_app.command("find")
def papers_find(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Resolve an internal or arXiv paper identifier exactly."""
    client = _client(ctx)
    try:
        _emit(client.call_tool("resolve_paper", {"identifier": identifier}), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@papers_app.command("show")
def papers_show(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show paper metadata, abstract, outline, figures, and repositories."""
    client = _client(ctx)
    try:
        resolved = client.call_tool("resolve_paper", {"identifier": identifier})
        if resolved.get("status") == "error":
            _emit(resolved, as_json)
            raise typer.Exit(1)
        payload = client.call_tool("get_paper_overview", {"paper_id": resolved["paper_id"]})
        _emit(payload, as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@papers_app.command("delete")
def papers_delete(
    ctx: typer.Context,
    paper_id: str,
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Submit a paper deletion job after confirmation."""
    if not yes and not typer.confirm(f"Delete paper {paper_id} and its owned chunks?"):
        raise typer.Abort()
    client = _client(ctx)
    try:
        _emit(client.submit_job("delete_paper", {"paper_id": paper_id}), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@search_app.command("paper")
def search_paper(
    ctx: typer.Context,
    query: str,
    top_k: int = typer.Option(10, min=1, max=50),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search for distinct papers."""
    client = _client(ctx)
    try:
        _emit(client.call_tool("search_papers", {"query": query, "top_k": top_k}), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@search_app.command("content")
def search_content(
    ctx: typer.Context,
    paper_id: str,
    query: str,
    top_k: int = typer.Option(10, min=1, max=20),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search multiple chunks inside one paper."""
    client = _client(ctx)
    try:
        _emit(
            client.call_tool(
                "search_paper_content",
                {"paper_id": paper_id, "query": query, "top_k": top_k},
            ),
            as_json,
        )
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@index_app.command("paper")
def index_paper(
    ctx: typer.Context,
    source: str,
    source_type: PaperSourceType = typer.Option(PaperSourceType.local, "--type"),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Submit a paper indexing job."""
    client = _client(ctx)
    try:
        _emit(
            client.submit_job(
                "index_paper",
                {"source": source, "source_type": source_type.value, "language": language},
            ),
            as_json,
        )
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@index_app.command("code")
def index_code(
    ctx: typer.Context,
    repo_url: str,
    paper_id: str = typer.Option(..., "--paper"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Submit a user-provided code repository indexing job."""
    client = _client(ctx)
    try:
        _emit(
            client.submit_job("index_code", {"repo_url": repo_url, "paper_id": paper_id}),
            as_json,
        )
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@jobs_app.command("list")
def jobs_list(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """List queued and recent jobs."""
    client = _client(ctx)
    try:
        _emit(client.list_jobs(), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


@jobs_app.command("cancel")
def jobs_cancel(
    ctx: typer.Context,
    job_id: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Cancel a queued job; running work may already be non-interruptible."""
    client = _client(ctx)
    try:
        _emit(client.cancel_job(job_id), as_json)
    except ServiceClientError as exc:
        _fail(exc)
    finally:
        client.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
