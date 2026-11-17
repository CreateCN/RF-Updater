from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from . import __version__
from .engine import Engine
from .i18n import from_environment, t, use
from .models import UpdaterError


def main(argv=None) -> int:
    use(from_environment())
    parser = argparse.ArgumentParser(description=t("cli.description"))
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, help=t("cli.root_help"))
    parser.add_argument("command", nargs="?", default="gui", choices=["gui", "check", "install", "status", "verify", "rollback", "launch"])
    args = parser.parse_args(argv)
    try:
        engine = Engine(args.root)
        if args.command == "gui":
            try:
                from .gui import launch_gui
            except ImportError as exc:
                raise UpdaterError(t("cli.missing_qt")) from exc
            launch_gui(engine)
        elif args.command == "status":
            print(json.dumps(engine.state(), ensure_ascii=False, indent=2))
        elif args.command == "check":
            release, status = engine.check()
            print(json.dumps({"status": status, "release": release.to_dict()}, ensure_ascii=False, indent=2))
        elif args.command == "install":
            release, _ = engine.check()
            print(json.dumps(engine.install(release, threading.Event(), console_progress), ensure_ascii=False, indent=2))
        elif args.command == "verify":
            print(t("cli.verify_ok", count=engine.verify(threading.Event(), console_progress)))
        elif args.command == "rollback":
            print(json.dumps(engine.rollback(), ensure_ascii=False, indent=2))
        elif args.command == "launch":
            print(t("cli.launched", pid=engine.launch()))
        return 0
    except KeyboardInterrupt:
        print("\n" + t("cli.interrupted"), file=sys.stderr)
        return 130
    except (UpdaterError, OSError) as exc:
        print(t("cli.error", error=exc), file=sys.stderr)
        return 1


_last_progress = 0.0


def console_progress(phase, done, total):
    import time
    global _last_progress
    now = time.monotonic()
    if now - _last_progress > .5 or done == total:
        _last_progress = now
        print(f"{phase}: {done} / {total if total is not None else '?'}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
