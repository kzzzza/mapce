"""MAPCE command-line entry point."""

from __future__ import annotations

import argparse
import json

from mapce.service.process import (
    ServiceProcessError,
    ensure_service,
    get_service_status,
    service_logs_path,
    stop_service,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mapce", description="Manage the local MAPCE service")
    parser.add_argument("--data-dir", help="Override MAPCE_DATA_DIR")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start or reuse the background service")
    subparsers.add_parser("serve-status", help="Show service status")
    kill = subparsers.add_parser("serve-kill", help="Stop the service")
    kill.add_argument("--force", action="store_true")
    subparsers.add_parser("serve-restart", help="Restart the service")
    logs = subparsers.add_parser("serve-logs", help="Show the service log path or tail logs")
    logs.add_argument("--tail", type=int, default=0)
    return parser


def _serialize_status(status: dict) -> dict:
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


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    data_dir = args.data_dir
    try:
        if args.command == "serve":
            info = ensure_service(data_dir)
            _print({"status": "ok", "running": True, "pid": info.pid, "url": info.base_url})
        elif args.command == "serve-status":
            _print(_serialize_status(get_service_status(data_dir)))
        elif args.command == "serve-kill":
            result = stop_service(data_dir, force=args.force)
            _print(result)
            if result.get("status") == "error":
                raise SystemExit(1)
        elif args.command == "serve-restart":
            result = stop_service(data_dir)
            if result.get("status") == "error":
                _print(result)
                raise SystemExit(1)
            info = ensure_service(data_dir)
            _print({"status": "ok", "running": True, "pid": info.pid, "url": info.base_url})
        elif args.command == "serve-logs":
            path = service_logs_path(data_dir)
            if args.tail > 0 and path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-args.tail:]))
            else:
                print(path)
        else:
            parser.print_help()
    except ServiceProcessError as exc:
        _print({"status": "error", "error_code": exc.error_code, "message": str(exc)})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
