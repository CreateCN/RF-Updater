# Localization Guide (0.5)

[中文](../localization.md) | **English**

## Mechanism

- The translation core is the standard-library-only module `rf_updater/i18n.py`; the engine and CLI never import Qt.
- Language resources are `rf_updater/locales/{zh-CN,zh-TW,en}.json`: flat key/value maps, ~340 keys. zh-CN is the source-language truth.
- `t(key, **params)`: look up the active language → `str.format` interpolation; missing keys fall back to zh-CN; a still-missing key returns the key name itself (visible but never fatal).
- Plurals: a value of `{"one": ..., "other": ...}` is selected by the `count` parameter (English distinguishes singular/plural; both Chinese forms are identical).
- Qt standard dialogs (QFileDialog, QMessageBox standard buttons) are translated by the GUI layer loading PySide6's bundled `qtbase_{en,zh_CN,zh_TW}.qm` via QTranslator — complementary to the app string system.

## Key conventions

- Namespaces: `engine.*`, `net.*`, `archive.*`, `storage.*`, `prefs.*` (engine/CLI errors and statuses), `gui.*` (window text), `task.*` (task phases and notices), `dir.*` (directory page), `cli.*` (command-line output).
- Semantic names, e.g. `engine.game_running`, `task.install_done`, `dir.cleanup_accept`.
- Dynamic values are always parameters: paths, URLs, ETags, SHA-256, numbers, dates. Templates use `{name}`; literal braces are written `{{}}`.
- Machine-readable content is never translated: `state.json`/receipt fields, logbook event keys, JSON output keys, build identifiers.
- Dates stay `%Y-%m-%d %H:%M`; size units stay B/KiB/MiB/GiB.
- Language names are shown in their own language (简体中文 / 繁體中文 / English) and do not follow the UI language.

## Detection and switching

- GUI initialization: `language` in `settings.json` (`null` = follow system) → `QLocale.system()`; Traditional Han script or TW/HK/MO → zh-TW, other Chinese → zh-CN, else → en.
- Follow-system mode re-detects on every launch; at runtime a `QEvent.LocaleChange` triggers an immediate switch (ignored when a language is manually fixed).
- CLI: `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`; none set → zh-CN.
- Switch flow: `i18n.use` → reload the qtbase translator → re-select fonts per language → `App.retranslate()` (static text) + `refresh()` (dynamic text) → rebuild the tray menu. No restart needed.
- Existing task notices keep the language they were produced in until the next operation (historical-message semantics).
- Fonts: zh-TW prefers Microsoft JhengHei UI / PingFang TC / Noto Sans CJK TC; zh-CN prefers Microsoft YaHei UI / PingFang SC / Noto Sans CJK SC; en uses the system default.

## Adding a language

1. Add the new catalog ID to `LOCALES` in `rf_updater/i18n.py` and extend the mapping in `match_name` / GUI detection.
2. Copy `zh-CN.json` to the new catalog file and translate every key; keep the key set and template parameters exactly identical.
3. Update the valid `language` values in `preferences.py`, `LANGUAGE_NAMES` and the qtbase mapping in `gui.py`, and the qm collection list in `scripts/build.py`.
4. Run `python -m scripts.i18n_report` to confirm no missing keys or parameter differences; run the full test suite.
5. Add assertions for the new language in `tests/test_i18n.py` and the GUI language scenarios.

## Maintenance and tests

- `python -m scripts.i18n_report`: scans source for `t("key")` usages, key literals passed to helpers, and f-string dynamic prefixes; reports missing/unused keys and parameter-set differences against the three catalogs; exits 1 on missing keys or parameter mismatches.
- `tests/test_i18n.py`: catalog key/parameter parity, fallback chain, plurals, interpolation safety, locale mapping, environment-variable priority, damaged catalogs.
- `tests/test_cli.py`: CLI language selection verified in subprocesses.
- `tests/test_gui.py`: language switching and persistence, initialization auto-detection, LocaleChange following, English minimum-window layout, no raw-key leakage.
- The suite pins zh-CN in `tests/__init__.py`; GUI tests additionally fix the language via settings, keeping assertions stable on any CI machine locale.

## Packaging

- Both setuptools package-data and PyInstaller `--add-data` collect `rf_updater/locales/*.json` and the three `qtbase_*.qm` files (the latter placed under `qt-translations/` inside the bundle).
- At runtime catalogs load via `importlib.resources` first, falling back to `Path(__file__)`; frozen builds load qtbase from `sys._MEIPASS/qt-translations`.
