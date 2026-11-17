"""Append-only JSON-lines diagnostics under the data root.

Each event opens and closes the file, so no persistent handle survives engine
or test-fixture lifetime. Rotation keeps three bounded backups.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 1_000_000
BACKUPS = 3


def log_path(root: Path) -> Path:
    return Path(root) / "logs" / "updater.log"


def record(root: Path, event: str, **fields) -> None:
    """Best effort: a failing diagnostic log must never break an operation.

    A disconnected saved directory must stay disconnected: never recreate the
    data root just to write diagnostics into it.
    """
    try:
        root = Path(root)
        if not root.is_dir():
            return
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            for index in range(BACKUPS - 1, 0, -1):
                source = path.with_name(f"updater.log.{index}")
                if source.exists():
                    os.replace(source, path.with_name(f"updater.log.{index + 1}"))
            os.replace(path, path.with_name("updater.log.1"))
        entry = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
