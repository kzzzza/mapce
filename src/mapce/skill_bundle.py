"""Install the bundled MAPCE research skills into agent skill directories."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INSTALL_MANIFEST = ".mapce-research-skills.json"
TARGET_DIRECTORIES = {
    "codex": Path(".codex") / "skills",
    "claude": Path(".claude") / "skills",
    "agents": Path(".agents") / "skills",
}


class SkillBundleError(RuntimeError):
    """A stable, user-facing skill installation error."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        conflicts: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.conflicts = conflicts or []


@dataclass(frozen=True)
class SkillBundle:
    root: Path
    version: str
    skills: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _default_bundle_root() -> Path:
    installed = Path(__file__).resolve().parent / "bundled_skills"
    if (installed / "bundle.json").is_file():
        return installed
    checkout = Path(__file__).resolve().parents[2] / "skills"
    if (checkout / "bundle.json").is_file():
        return checkout
    raise SkillBundleError(
        "skill_bundle_missing",
        "The MAPCE research skill bundle is missing from this installation.",
    )


def load_bundle(bundle_root: Path | None = None) -> SkillBundle:
    root = (bundle_root or _default_bundle_root()).resolve()
    manifest_path = root / "bundle.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillBundleError(
            "invalid_skill_bundle",
            f"Cannot read skill bundle manifest: {manifest_path}",
        ) from exc

    version = str(payload.get("version") or "").strip()
    skills = tuple(str(value).strip() for value in payload.get("skills", []))
    if not version or not skills or len(skills) != len(set(skills)):
        raise SkillBundleError("invalid_skill_bundle", "Skill bundle manifest is invalid.")
    missing = [name for name in skills if not (root / name / "SKILL.md").is_file()]
    if missing:
        raise SkillBundleError(
            "invalid_skill_bundle",
            f"Skill bundle is missing SKILL.md for: {', '.join(missing)}",
        )
    return SkillBundle(root=root, version=version, skills=skills)


def resolve_destination(
    *,
    target: str | None = None,
    path: Path | None = None,
    home: Path | None = None,
) -> Path:
    if bool(target) == bool(path):
        raise SkillBundleError(
            "skill_destination_required",
            "Choose exactly one destination with --target or --path.",
        )
    if path is not None:
        return path.expanduser().resolve()
    normalized = str(target).lower()
    relative = TARGET_DIRECTORIES.get(normalized)
    if relative is None:
        allowed = ", ".join(sorted(TARGET_DIRECTORIES))
        raise SkillBundleError(
            "invalid_skill_target",
            f"Unknown skill target '{target}'. Expected one of: {allowed}.",
        )
    return ((home or Path.home()) / relative).resolve()


def _bundle_files(bundle: SkillBundle) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for skill in bundle.skills:
        for source in sorted((bundle.root / skill).rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                relative = source.relative_to(bundle.root).as_posix()
                files[relative] = source
    return files


def _read_install_manifest(destination: Path) -> dict[str, Any] | None:
    path = destination / INSTALL_MANIFEST
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _has_symlink_component(destination: Path, installed: Path) -> bool:
    current = installed
    while current != destination:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def bundle_summary(bundle_root: Path | None = None) -> dict[str, Any]:
    bundle = load_bundle(bundle_root)
    return {
        "status": "ok",
        "bundle_version": bundle.version,
        "count": len(bundle.skills),
        "skills": list(bundle.skills),
    }


def bundle_status(
    *,
    target: str | None = None,
    path: Path | None = None,
    home: Path | None = None,
    bundle_root: Path | None = None,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_root)
    destination = resolve_destination(target=target, path=path, home=home)
    expected = _bundle_files(bundle)
    previous = _read_install_manifest(destination) or {}
    previous_files = previous.get("files") if isinstance(previous.get("files"), dict) else {}
    states: dict[str, str] = {}
    for relative, source in expected.items():
        installed = destination / relative
        if _has_symlink_component(destination, installed):
            states[relative] = "unmanaged"
        elif not installed.is_file():
            states[relative] = "missing"
        elif _sha256(installed) == _sha256(source):
            states[relative] = "current"
        elif relative in previous_files:
            states[relative] = "modified"
        else:
            states[relative] = "unmanaged"
    counts = {
        state: sum(value == state for value in states.values())
        for state in ("current", "missing", "modified", "unmanaged")
    }
    return {
        "status": "ok",
        "destination": str(destination),
        "bundle_version": bundle.version,
        "installed_version": previous.get("bundle_version"),
        "counts": counts,
        "skills": list(bundle.skills),
        "files": states,
    }


def install_bundle(
    *,
    target: str | None = None,
    path: Path | None = None,
    update: bool = False,
    home: Path | None = None,
    bundle_root: Path | None = None,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_root)
    destination = resolve_destination(target=target, path=path, home=home)
    sources = _bundle_files(bundle)
    previous = _read_install_manifest(destination) or {}
    previous_files = previous.get("files") if isinstance(previous.get("files"), dict) else {}

    conflicts: list[str] = []
    changes: list[tuple[Path, Path]] = []
    for relative, source in sources.items():
        installed = destination / relative
        source_hash = _sha256(source)
        if _has_symlink_component(destination, installed):
            conflicts.append(relative)
            continue
        if not installed.exists():
            changes.append((source, installed))
            continue
        if not installed.is_file():
            conflicts.append(relative)
            continue
        installed_hash = _sha256(installed)
        if installed_hash == source_hash:
            continue
        previous_hash = previous_files.get(relative)
        if update and previous_hash and installed_hash == previous_hash:
            changes.append((source, installed))
        else:
            conflicts.append(relative)

    if conflicts:
        raise SkillBundleError(
            "skill_install_conflict",
            "Skill installation stopped because destination files differ from the bundle.",
            conflicts=sorted(conflicts),
        )

    hashes = {relative: _sha256(source) for relative, source in sources.items()}
    if (
        not changes
        and previous.get("bundle_version") == bundle.version
        and previous.get("skills") == list(bundle.skills)
        and previous_files == hashes
    ):
        return {
            "status": "ok",
            "destination": str(destination),
            "bundle_version": bundle.version,
            "skills": list(bundle.skills),
            "files_copied": 0,
            "message": "MAPCE research skills are already current.",
        }

    destination.mkdir(parents=True, exist_ok=True)
    for source, installed in changes:
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, installed)

    manifest = {
        "schema_version": 1,
        "bundle_version": bundle.version,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "skills": list(bundle.skills),
        "files": hashes,
    }
    (destination / INSTALL_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "destination": str(destination),
        "bundle_version": bundle.version,
        "skills": list(bundle.skills),
        "files_copied": len(changes),
        "message": "MAPCE research skills installed.",
    }
