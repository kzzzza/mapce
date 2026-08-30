from __future__ import annotations

import subprocess
import sys


def test_importing_stdio_proxy_does_not_import_database_or_embedding():
    command = [
        sys.executable,
        "-c",
        (
            "import sys; import mapce.mcp.server; "
            "print(int('lancedb' in sys.modules), "
            "int('fastembed' in sys.modules), "
            "int('mapce.core.embedding' in sys.modules))"
        ),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    assert result.stdout.strip() == "0 0 0"
