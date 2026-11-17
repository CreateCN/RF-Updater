"""Observe a real native updater/game window, then stop only the process we start.

Linux: xvfb-run -a python -m scripts.smoke_native dist/RF-Updater/RF-Updater
Linux game acceptance: xvfb-run -a python -m scripts.smoke_native --game-root /tmp/rf-live-test
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from rf_updater.engine import Engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", nargs="?", type=Path)
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--launcher", type=Path, help="For --game-root, launch through this bundled updater")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rf-native-smoke-") as temp:
        processes = []
        game_pid = None
        original = subprocess.Popen
        env = {**os.environ, "XDG_DATA_HOME": str(Path(temp) / "data"),
               "XDG_CONFIG_HOME": str(Path(temp) / "config"), "XDG_CACHE_HOME": str(Path(temp) / "cache")}
        def track(*positional, **keywords):
            keywords["env"] = {**keywords.get("env", {}), **env}
            process = original(*positional, **keywords)
            processes.append(process)
            return process
        output = Path(temp) / "smoke.log"
        try:
            if args.game_root:
                if args.launcher:
                    result = subprocess.run([str(args.launcher.resolve()), "--root", str(args.game_root), "launch"],
                                            env=env, capture_output=True, text=True, check=True, timeout=25)
                    match = re.search(r"PID (\d+)", result.stdout)
                    if not match:
                        raise AssertionError(result.stdout + result.stderr)
                    pid = game_pid = int(match[1])
                    process = None
                else:
                    with patch("rf_updater.engine.subprocess.Popen", side_effect=track):
                        pid = Engine(args.game_root).launch()
                    process = processes[0]
            else:
                if not args.binary:
                    parser.error("binary or --game-root is required")
                with output.open("wb") as log:
                    process = track([str(args.binary.resolve()), "--root", str(Path(temp) / "updater")],
                                    stdout=log, stderr=log, start_new_session=True)
                pid = process.pid
            time.sleep(6 if args.game_root else 2)
            if process is not None and process.poll() is not None:
                log = args.game_root / "logs/game.log" if args.game_root else output
                raise AssertionError(f"Process exited early ({process.returncode}):\n{log.read_text(errors='replace')[-8000:]}")
            if game_pid:
                os.kill(game_pid, 0)
                # An exited orphan can remain as a zombie until the host reaps it.
                status = Path(f"/proc/{game_pid}/stat").read_text().split(")", 1)[1].split()[0]
                if status == "Z":
                    raise AssertionError("Bundled launcher child exited early")
            if args.screenshot:
                from PIL import ImageGrab
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                ImageGrab.grab().save(args.screenshot)
            print(f"Native window remained running, PID {pid}. Test will now close its own process.")
        finally:
            if game_pid:
                try:
                    os.killpg(game_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for process in processes:
                if process.poll() is None:
                    if sys.platform == "win32":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Some game engines do not exit on SIGTERM while a modal is
                    # open. Force-stop only this test's isolated process group.
                    if sys.platform == "win32":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    print("Test cleanup required SIGKILL for its own process group.")


if __name__ == "__main__":
    main()
