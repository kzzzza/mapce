"""Run the singleton MAPCE HTTP service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn

from mapce import __version__

from .app import create_app
from .runtime import (
    ServiceInfo,
    ServiceLock,
    data_dir_hash,
    normalize_data_dir,
    runtime_paths,
    write_service_info,
    write_token,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MAPCE local service")
    parser.add_argument("--data-dir")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MAPCE_SERVICE_PORT", "8765")))
    return parser.parse_args()


async def serve(data_dir: str | Path | None, host: str, port: int) -> int:
    normalized = normalize_data_dir(data_dir)
    paths = runtime_paths(normalized)
    lock = ServiceLock(paths.lock)
    if not lock.acquire():
        logging.error("A MAPCE service already owns this data directory.")
        return 73

    paths.directory.mkdir(parents=True, exist_ok=True)
    token = write_token(paths.token)
    info = ServiceInfo(
        service_id=uuid4().hex,
        pid=os.getpid(),
        host=host,
        port=port,
        data_dir=str(normalized),
        data_dir_hash=data_dir_hash(normalized),
        version=__version__,
        started_at=datetime.now(timezone.utc).isoformat(),
        token_file=str(paths.token),
    )
    write_service_info(paths.info, info)
    os.environ["MAPCE_DATA_DIR"] = str(normalized)
    os.environ["MAPCE_SERVICE_OWNER_ID"] = info.service_id

    server_holder: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        server_holder["server"].should_exit = True

    app = create_app(info, token, shutdown_callback=request_shutdown)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("MAPCE_LOG_LEVEL", "INFO").lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server
    try:
        await server.serve()
        return 0 if server.started else 98
    finally:
        for path in (paths.info, paths.token):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        lock.release()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    raise SystemExit(asyncio.run(serve(args.data_dir, args.host, args.port)))


if __name__ == "__main__":
    main()
