"""Build a native desktop bundle on the current OS; never cross-compile."""
from __future__ import annotations

import hashlib
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

from rf_updater.models import native_platform


def main():
    import certifi
    target = native_platform()
    root = Path(__file__).resolve().parents[1]
    work = root / "build"
    work.mkdir(exist_ok=True)
    ca_bundle = work / "ca-bundle.pem"
    shutil.copy2(certifi.where(), ca_bundle)
    ca_license = work / "ca-bundle-LICENSE.txt"
    distribution = importlib.metadata.distribution("certifi")
    license_text = distribution.read_text("licenses/LICENSE") or distribution.read_text("LICENSE")
    if not license_text:
        raise RuntimeError("Cannot locate the certifi CA bundle license")
    ca_license.write_text("Mozilla CA certificate bundle, distributed by certifi\nSource: https://github.com/certifi/python-certifi\n\n" + license_text, encoding="utf-8")
    # Qt's own standard-dialog translations for the supported languages.
    import PySide6
    qt_translations = Path(PySide6.__file__).resolve().parent / "Qt" / "translations"
    qt_work = work / "qt-translations"
    qt_work.mkdir(exist_ok=True)
    for name in ("qtbase_en.qm", "qtbase_zh_CN.qm", "qtbase_zh_TW.qm"):
        source = qt_translations / name
        if source.is_file():
            shutil.copy2(source, qt_work / name)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--windowed", "--name", "RF-Updater", "--noupx",
        "--additional-hooks-dir", str(root / "scripts/hooks"),
        "--exclude-module", "tkinter",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtPdf",
        "--add-data", f"{ca_bundle}:.",
        "--add-data", f"{ca_license}:.",
        "--add-data", f"{root / 'rf_updater' / 'locales'}:rf_updater/locales",
        "--add-data", f"{qt_work}:qt-translations",
        "--add-data", f"{root / 'docs/third-party'}:third-party",
        "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
        "--specpath", str(root / "build"), str(root / "run_updater.py"),
    ], cwd=root, check=True)
    dist = root / "dist"
    if target == "macos":
        # ditto preserves executable modes and framework symlinks in .app bundles.
        artifact = dist / "RF-Updater-macos-arm64.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(dist / "RF-Updater.app"), str(artifact)], check=True)
    else:
        bundle = dist / "RF-Updater"
        shutil.copy2(root / "resources/icon.svg", bundle / "icon.svg")
        shutil.copy2(root / "README.md", bundle / "README.md")
        shutil.copy2(root / "LICENSE", bundle / "LICENSE")
        shutil.copytree(root / "docs", bundle / "docs", dirs_exist_ok=True)
        archive = shutil.make_archive(str(dist / f"RF-Updater-{target}-x64"), "zip" if target == "windows" else "gztar", root_dir=dist, base_dir="RF-Updater")
        artifact = Path(archive)
    with artifact.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    artifact.with_name(artifact.name + ".sha256").write_text(f"{checksum}  {artifact.name}\n", encoding="ascii")
    print(f"Built {artifact}")


if __name__ == "__main__":
    main()
