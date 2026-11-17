"""Report translation coverage: scan t("key") usages against the catalogs.

python -m scripts.i18n_report
Exits non-zero when a used key is missing from any locale or parameter sets differ.
"""
from __future__ import annotations

import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-CN", "zh-TW", "en")
USAGE = re.compile(r'\bt\(\s*"([a-z0-9_.]+)"')
DYNAMIC = re.compile(r'f"([a-z0-9_.]+)\.\{')
KEY_LITERAL = re.compile(r'"([a-z][a-z0-9]*(?:\.[a-z0-9_]+)+)"')


def parameters(value) -> set[str]:
    texts = value.values() if isinstance(value, dict) else [value]
    result = set()
    for text in texts:
        if isinstance(text, str):
            result.update(field for _, field, _, _ in string.Formatter().parse(text) if field)
    return result


def main() -> int:
    used = set()
    dynamic_prefixes = set()
    literals = set()
    for path in sorted((ROOT / "rf_updater").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        used.update(USAGE.findall(text))
        dynamic_prefixes.update(DYNAMIC.findall(text))
        literals.update(KEY_LITERAL.findall(text))
    catalogs = {}
    for locale in LOCALES:
        catalogs[locale] = json.loads((ROOT / "rf_updater" / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
    all_keys = set(catalogs["zh-CN"])
    # Keys passed through helpers/dicts appear as plain literals; f-string keys
    # are built from a prefix, so every catalog key under that prefix counts.
    used |= literals & all_keys
    used |= {key for key in all_keys if any(key.startswith(prefix + ".") for prefix in dynamic_prefixes)}
    problems = []
    for key in sorted(used):
        for locale in LOCALES:
            if key not in catalogs[locale]:
                problems.append(f"missing: {locale} {key}")
        reference = parameters(catalogs["zh-CN"].get(key, ""))
        for locale in LOCALES:
            if key in catalogs[locale] and parameters(catalogs[locale][key]) != reference:
                problems.append(f"params differ: {locale} {key}")
    for locale in LOCALES:
        for key in sorted(set(catalogs[locale]) - used):
            print(f"note: unused key in {locale}: {key}")
    if problems:
        print("\n".join(problems))
        return 1
    print(f"OK: {len(used)} used keys present with matching parameters in {len(LOCALES)} locales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
