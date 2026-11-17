import json
import os
import string
import unittest
from pathlib import Path
from unittest.mock import patch

from rf_updater import i18n

LOCALES = ("zh-CN", "zh-TW", "en")


def catalogs():
    base = Path(i18n.__file__).resolve().parent / "locales"
    return {locale: json.loads((base / f"{locale}.json").read_text(encoding="utf-8")) for locale in LOCALES}


def parameters(value):
    texts = value.values() if isinstance(value, dict) else [value]
    result = set()
    for text in texts:
        if isinstance(text, str):
            result.update(field for _, field, _, _ in string.Formatter().parse(text) if field)
    return result


class I18nTests(unittest.TestCase):
    def setUp(self):
        i18n.use("zh-CN")
        self.addCleanup(i18n.use, "zh-CN")

    def test_catalogs_have_identical_keys_and_parameters(self):
        data = catalogs()
        base = set(data["zh-CN"])
        for locale in LOCALES:
            self.assertEqual(set(data[locale]), base, locale)
        for key in base:
            reference = parameters(data["zh-CN"][key])
            for locale in LOCALES:
                self.assertEqual(parameters(data[locale][key]), reference, f"{locale} {key}")

    def test_translation_and_fallback_chain(self):
        i18n.use("en")
        self.assertEqual(i18n.t("engine.not_installed"), "Install the game first.")
        i18n.use("zh-TW")
        self.assertEqual(i18n.t("engine.not_installed"), "請先安裝遊戲。")
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")

    def test_missing_key_falls_back_to_source_language(self):
        data = catalogs()
        with patch.object(i18n, "_catalogs", {"en": {}, "zh-CN": data["zh-CN"], "zh-TW": {}}), \
             patch.object(i18n, "_loaded", True):
            i18n.use("en")
            self.assertEqual(i18n.t("engine.not_installed"), "请先安装游戏。")

    def test_plurals_select_by_count(self):
        i18n.use("en")
        self.assertEqual(i18n.t("task.cleanup_done", count=1), "Cleaned up 1 item")
        self.assertEqual(i18n.t("task.cleanup_done", count=3), "Cleaned up 3 items")
        i18n.use("zh-CN")
        self.assertEqual(i18n.t("task.cleanup_done", count=1), "已清理 1 个项目")
        self.assertEqual(i18n.t("task.cleanup_done", count=3), "已清理 3 个项目")

    def test_interpolation_and_missing_params_are_safe(self):
        i18n.use("en")
        self.assertEqual(i18n.t("cli.launched", pid=42), "Game launched, PID 42")
        # A missing parameter must not raise; the raw template is returned.
        self.assertIn("{pid}", i18n.t("cli.launched"))

    def test_match_name_maps_machine_locales(self):
        cases = {"zh_CN": "zh-CN", "zh_SG": "zh-CN", "zh_Hans": "zh-CN", "zh": "zh-CN",
                 "zh_TW": "zh-TW", "zh_HK": "zh-TW", "zh_MO": "zh-TW", "zh_Hant": "zh-TW",
                 "zh-Hant-TW": "zh-TW", "en_US": "en", "en": "en", "ja_JP": "en",
                 "C": "en", "": "en", "POSIX": "en"}
        for name, expected in cases.items():
            self.assertEqual(i18n.match_name(name), expected, name)

    def test_from_environment_priority(self):
        env = {"RF_UPDATER_LANG": "zh-TW", "LC_ALL": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(i18n.from_environment(), "zh-TW")
        env = {"LC_ALL": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(i18n.from_environment(), "en")
        env = {"LANG": "zh_TW.UTF-8"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(i18n.from_environment(), "zh-TW")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(i18n.from_environment(), "zh-CN")

    def test_use_rejects_unknown_locale(self):
        self.assertEqual(i18n.use("fr"), "zh-CN")
        self.assertEqual(i18n.current(), "zh-CN")

    def test_damaged_catalog_does_not_crash(self):
        i18n.reload()
        with patch.object(i18n, "_read_catalog", side_effect=OSError("unreadable")):
            self.assertEqual(i18n.t("engine.not_installed"), "engine.not_installed")
        i18n.reload()
        self.assertEqual(i18n.t("engine.not_installed"), "请先安装游戏。")


if __name__ == "__main__":
    unittest.main()
