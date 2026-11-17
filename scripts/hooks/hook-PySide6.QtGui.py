"""Collect desktop Qt plugins for the launcher's code-drawn UI, not document viewers."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
desktop_platforms = {
    "libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so",
    "qwindows.dll", "qoffscreen.dll", "qminimal.dll",
    "libqcocoa.dylib", "libqoffscreen.dylib", "libqminimal.dylib",
}


def needed_plugin(source, destination):
    parts = Path(destination).parts
    # Keep SVG support for themed filesystem icons in the folder picker. Document
    # plugins such as PDF would pull unrelated engines into this launcher.
    if "imageformats" in parts or "iconengines" in parts:
        return "qsvg" in Path(source).name.lower()
    if "platforms" in parts:
        return Path(source).name in desktop_platforms
    return "virtualkeyboard" not in Path(source).name.lower()


binaries = [(source, destination) for source, destination in binaries if needed_plugin(source, destination)]
