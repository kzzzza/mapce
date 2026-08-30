from __future__ import annotations

import os

from typer.testing import CliRunner

from mapce import cli


runner = CliRunner()


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.closed = False
        self.__class__.instances.append(self)

    def call_tool(self, name, arguments):
        return {"status": "ok", "name": name, "arguments": arguments}

    def submit_job(self, name, arguments):
        return {"status": "ok", "job": {"job_id": "j1", "tool": name, "arguments": arguments}}

    def close(self):
        self.closed = True


def test_no_arguments_launches_tui_and_passes_data_dir(monkeypatch, tmp_path):
    launched = []

    def fake_run(self):
        launched.append(self.api.data_dir)

    monkeypatch.setattr("mapce.tui.app.MapceTUI.run", fake_run)
    monkeypatch.setattr("mapce.tui.app.MapceClient", FakeClient)

    result = runner.invoke(cli.app, ["--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert launched == [tmp_path]


def test_paper_find_outputs_machine_readable_json(monkeypatch):
    monkeypatch.setattr(cli, "MapceClient", FakeClient)

    result = runner.invoke(cli.app, ["papers", "find", "2412.04368", "--json"])

    assert result.exit_code == 0
    assert '"name": "resolve_paper"' in result.stdout
    assert '"identifier": "2412.04368"' in result.stdout
    assert FakeClient.instances[-1].closed is True


def test_index_command_submits_background_job(monkeypatch):
    monkeypatch.setattr(cli, "MapceClient", FakeClient)

    result = runner.invoke(
        cli.app,
        ["index", "paper", "2501.00001", "--type", "arxiv", "--json"],
    )

    assert result.exit_code == 0
    assert '"tool": "index_paper"' in result.stdout
    assert '"source_type": "arxiv"' in result.stdout


def test_config_set_env_then_regular_command_loads_it(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MAPCE_CLI_CONFIG_TEST=loaded\n", encoding="utf-8")
    monkeypatch.delenv("MAPCE_CLI_CONFIG_TEST", raising=False)
    monkeypatch.setattr(cli, "MapceClient", FakeClient)

    saved = runner.invoke(cli.app, ["config", "set-env", str(env_file)])
    shown = runner.invoke(cli.app, ["config", "show"])
    stats = runner.invoke(cli.app, ["stats", "--json"])

    assert saved.exit_code == 0
    assert str(env_file) in saved.stdout
    assert shown.exit_code == 0
    assert '"source": "config"' in shown.stdout
    assert stats.exit_code == 0
    assert os.environ["MAPCE_CLI_CONFIG_TEST"] == "loaded"
