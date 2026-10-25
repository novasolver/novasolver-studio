"""Three-language message lookup. Keys are ASCII; missing keys fall back to English, then to the key."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LANGS = ("ja", "en", "zh")
_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def _table(lang: str) -> dict:
    return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def lang_of(lang: str | None) -> str:
    return lang if lang in LANGS else "ja"


def t(key: str, lang: str | None = "ja", **kw) -> str:
    lang = lang_of(lang)
    s = _table(lang).get(key) or _table("en").get(key) or key
    try:
        return s.format(**kw) if kw else s
    except (KeyError, ValueError, IndexError):
        return s


def all3(key: str, **kw) -> dict:
    return {l: t(key, l, **kw) for l in LANGS}
