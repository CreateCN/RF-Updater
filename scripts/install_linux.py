"""Install a verified local Linux bundle per user, preserving older versions and game data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from rf_updater import __version__
from rf_updater.models import native_platform

MARKER = '# RF-Updater user launcher'
DESKTOP_MARKER = 'X-RF-Updater-Managed=true'


def atomic_text(path: Path, value: str, mode: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', prefix=path.name+'.', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
            temporary.chmod(mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='安装本地 RF-Updater Linux 包到用户目录')
    parser.add_argument('--archive', type=Path, default=Path('dist/RF-Updater-linux-x64.tar.gz'))
    parser.add_argument('--launch', action='store_true')
    args = parser.parse_args()
    if native_platform() != 'linux':
        parser.error('This installer is for Linux x64')
    archive = args.archive.resolve()
    expected = archive.with_name(archive.name+'.sha256').read_text(encoding='ascii').split()[0]
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not re.fullmatch('[0-9a-f]{64}', expected) or expected != digest:
        raise SystemExit('安装包摘要不匹配，未修改已有程序。')
    install_base = Path.home()/'.local/opt/rf-updater'
    install_base.mkdir(parents=True, exist_ok=True)
    destination = install_base/f'{__version__}-{digest[:8]}'
    binary = destination/'RF-Updater'
    launcher = Path.home()/'.local/bin/rf-updater'
    applications = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'applications'
    desktop = applications/'rf-updater-community.desktop'
    # Do not overwrite unrelated launchers, even when the archive is valid.
    if launcher.exists() and MARKER not in launcher.read_text(errors='replace'):
        raise SystemExit(f'启动文件已被其他程序占用：{launcher}')
    if desktop.exists() and DESKTOP_MARKER not in desktop.read_text(errors='replace'):
        raise SystemExit(f'菜单文件已被其他程序占用：{desktop}')
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='.install-', dir=install_base) as tmp:
            with tarfile.open(archive) as package:
                package.extractall(tmp, filter='data')
            candidate = Path(tmp)/'RF-Updater'
            result = subprocess.run([str(candidate/'RF-Updater'), '--version'], capture_output=True, text=True, timeout=15, check=True)
            if result.stdout.strip() != __version__:
                raise SystemExit('安装包版本与安装脚本不匹配。')
            os.replace(candidate, destination)
    atomic_text(launcher, '#!/bin/sh\n'+MARKER+'\nexec '+shlex.quote(str(binary))+' "$@"\n', 0o755)
    icon = destination/'icon.svg'
    # Desktop Entry escaping happens before Exec argument parsing.
    executable = str(binary).replace('\\', '\\\\\\\\').replace('"', '\\\\"').replace('$', '\\\\$').replace('`', '\\\\`').replace('%', '%%')
    entry = ('[Desktop Entry]\nType=Application\nName=Rocket Foundry 更新器\n'
             'Name[zh_TW]=Rocket Foundry 更新器\nName[en]=Rocket Foundry Updater\n'
             'Comment=下载、更新与启动 Rocket Foundry\n'
             'Comment[zh_TW]=下載、更新與啟動 Rocket Foundry\n'
             'Comment[en]=Download, update and launch Rocket Foundry\n'
             f'Exec="{executable}"\nIcon={icon if icon.exists() else "applications-games"}\n'
             'Terminal=false\nCategories=Game;Utility;\n'+DESKTOP_MARKER+'\n')
    atomic_text(desktop, entry, 0o644)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(applications)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info = {'version': __version__, 'binary': str(binary), 'launcher': str(launcher), 'desktop_entry': str(desktop)}
    if args.launch:
        logs = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'rf-updater'
        logs.mkdir(parents=True, exist_ok=True)
        log = logs/'launcher.log'
        with log.open('ab') as output:
            process = subprocess.Popen([str(binary)], cwd=destination, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, start_new_session=True)
        info.update(pid=process.pid, log=str(log))
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
