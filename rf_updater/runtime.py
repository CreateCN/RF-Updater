"""Keep the updater's bundled shared libraries out of external applications."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path


def external_environment() -> dict[str, str]:
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        return env
    if sys.platform.startswith("linux"):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is not None:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    bundle = str(getattr(sys, "_MEIPASS", ""))
    for key in ("PATH", "DYLD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"):
        if bundle and key in env:
            env[key] = os.pathsep.join(part for part in env[key].split(os.pathsep)
                                       if part != bundle and not part.startswith(bundle + os.sep))
            if not env[key] and key not in {"PATH", "DYLD_LIBRARY_PATH"}:
                env.pop(key)
    return env


@contextlib.contextmanager
def external_libraries():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel.GetDllDirectoryW.restype = ctypes.c_uint32
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    size = kernel.GetDllDirectoryW(0, None)
    buffer = ctypes.create_unicode_buffer(size + 1)
    kernel.GetDllDirectoryW(len(buffer), buffer)
    if not kernel.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value or None)


def open_external(destination: str | Path) -> None:
    with external_libraries():
        if sys.platform == "win32":
            os.startfile(str(destination))
        else:
            command = "open" if sys.platform == "darwin" else "xdg-open"
            process = subprocess.Popen([command, str(destination)], env=external_environment())
            threading.Thread(target=process.wait, daemon=True).start()
