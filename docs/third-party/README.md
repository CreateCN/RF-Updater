# Third-party components in the standalone updater

The application source is MIT licensed. Shared libraries and data retain their own licenses.

- **PySide6 and Shiboken6 6.12.0**, copyright The Qt Company Ltd. and contributors. Used under LGPL-3.0; corresponding sources: <https://code.qt.io/pyside/pyside-setup.git/tag/?h=v6.12.0>. Full LGPL/GPL texts are included in `qtbase-6.12.0/LICENSES/`.
- **Qt 6.12.0** desktop Core, Gui, Widgets and their platform dependencies, copyright The Qt Company Ltd. and contributors. Shared libraries are distributed dynamically in the onedir bundle. Sources: <https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/>. The launcher does not prohibit modification or reverse engineering of the LGPL-covered libraries for debugging such modifications.
- `qtbase-6.12.0/` contains unchanged license texts and third-party attribution manifests from the matching official QtBase source archive. `SOURCE.json` records the source URL and verified SHA-256. This is a superset of QtBase notices, not a claim that every listed component is distributed.
- **Mozilla public CA data via certifi 2026.10.23**: the original bundle and its license are included as `ca-bundle.pem` and `ca-bundle-LICENSE.txt` in the application resources. Sources: <https://github.com/certifi/python-certifi/tree/2026.10.23>.
- **Python** and the **PyInstaller bootloader** are included by PyInstaller under their respective distribution terms and bootloader exception. The Qt license bundle also contains the applicable open-source license texts for QtBase third-party components.

The native bundle's Qt shared libraries remain separate files. Replacement libraries must match the platform, Qt version and ABI expected by the bundled Python bindings. No game binaries or game artwork are included.
