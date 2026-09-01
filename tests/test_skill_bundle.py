from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mapce import cli
from mapce.skill_bundle import (
    SkillBundleError,
    bundle_status,
    bundle_summary,
    install_bundle,
    resolve_destination,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"


def test_skill_bundle_has_six_valid_skills_and_evals():
    summary = bundle_summary(SKILLS_ROOT)

    assert summary["count"] == 6
    for name in summary["skills"]:
        skill_root = SKILLS_ROOT / name
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        _, frontmatter, body = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert metadata["name"] == name
        assert metadata["description"]
        assert len(body.splitlines()) < 500
        evals = json.loads((skill_root / "evals/evals.json").read_text(encoding="utf-8"))
        assert evals["skill_name"] == name
        assert len(evals["evals"]) >= 2
        for case in evals["evals"]:
            assert case["prompt"]
            assert case["expectations"]


def test_install_is_idempotent_and_status_reports_current(tmp_path):
    destination = tmp_path / "skills"

    first = install_bundle(path=destination, bundle_root=SKILLS_ROOT)
    manifest_before = (destination / ".mapce-research-skills.json").read_text(encoding="utf-8")
    second = install_bundle(path=destination, bundle_root=SKILLS_ROOT)
    manifest_after = (destination / ".mapce-research-skills.json").read_text(encoding="utf-8")
    status = bundle_status(path=destination, bundle_root=SKILLS_ROOT)

    assert first["files_copied"] > 0
    assert second["files_copied"] == 0
    assert manifest_after == manifest_before
    assert status["counts"]["current"] == first["files_copied"]
    assert status["counts"]["missing"] == 0
    assert status["counts"]["modified"] == 0


def test_install_refuses_unmanaged_or_locally_modified_files(tmp_path):
    destination = tmp_path / "skills"
    install_bundle(path=destination, bundle_root=SKILLS_ROOT)
    changed = destination / "mapce-paper-reading/SKILL.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")

    with pytest.raises(SkillBundleError) as normal:
        install_bundle(path=destination, bundle_root=SKILLS_ROOT)
    with pytest.raises(SkillBundleError) as update:
        install_bundle(path=destination, update=True, bundle_root=SKILLS_ROOT)

    assert normal.value.error_code == "skill_install_conflict"
    assert update.value.error_code == "skill_install_conflict"
    assert "mapce-paper-reading/SKILL.md" in update.value.conflicts


def test_install_refuses_symlinked_skill_directory(tmp_path):
    destination = tmp_path / "skills"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "mapce-paper-reading").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SkillBundleError) as error:
        install_bundle(path=destination, bundle_root=SKILLS_ROOT)

    assert error.value.error_code == "skill_install_conflict"
    assert any(value.startswith("mapce-paper-reading/") for value in error.value.conflicts)
    assert not any(outside.iterdir())


def test_update_replaces_only_unchanged_installed_files(tmp_path):
    source = tmp_path / "bundle"
    shutil.copytree(SKILLS_ROOT, source)
    destination = tmp_path / "installed"
    install_bundle(path=destination, bundle_root=source)
    source_skill = source / "mapce-paper-reading/SKILL.md"
    source_skill.write_text(source_skill.read_text(encoding="utf-8") + "\nNew bundled line.\n", encoding="utf-8")
    manifest = json.loads((source / "bundle.json").read_text(encoding="utf-8"))
    manifest["version"] = "0.1.1"
    (source / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = install_bundle(path=destination, update=True, bundle_root=source)

    assert result["bundle_version"] == "0.1.1"
    assert result["files_copied"] == 1
    assert (destination / "mapce-paper-reading/SKILL.md").read_text(encoding="utf-8").endswith(
        "New bundled line.\n"
    )


def test_destination_requires_exactly_one_selector(tmp_path):
    with pytest.raises(SkillBundleError) as missing:
        resolve_destination()
    with pytest.raises(SkillBundleError) as duplicate:
        resolve_destination(target="codex", path=tmp_path)

    assert missing.value.error_code == "skill_destination_required"
    assert duplicate.value.error_code == "skill_destination_required"
    assert resolve_destination(target="codex", home=tmp_path) == tmp_path / ".codex/skills"


def test_cli_skills_list_does_not_require_env_file(monkeypatch):
    monkeypatch.setattr(cli, "load_configured_env", lambda **_: (_ for _ in ()).throw(AssertionError))

    result = CliRunner().invoke(cli.app, ["skills", "list"])

    assert result.exit_code == 0
    assert '"count": 6' in result.stdout
