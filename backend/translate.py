"""Translate English company descriptions to Hebrew via Claude Haiku 4.5.

Design:
  - Cache hits never spend API budget. The cache is keyed by SHA-1 of the
    source text, so the same company description from any symbol resolves
    instantly after the first translation.
  - Cache is persisted on disk (`backend/data/translations.json`) so it
    survives backend restarts.
  - Graceful fallback: if ANTHROPIC_API_KEY isn't set or the API errors out,
    return None and the frontend will display the English original.
  - Prompt caching on the system block — the same instruction prefix is reused
    across every translation, so the cache-write premium amortizes immediately.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Lock

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent / "data" / "translations.json"
CACHE_FILE.parent.mkdir(exist_ok=True)

_cache: dict[str, str] = {}
_cache_loaded = False
_cache_lock = Lock()

# Tight system instruction reused across every call → strong cache hit rate.
_SYSTEM_PROMPT = (
    "אתה מתרגם תקצירי חברות ציבוריות מאנגלית לעברית. "
    "כתוב בעברית ברורה, מקצועית, זורמת — לא תרגום מילולי. "
    "שמור באנגלית: שמות חברות, מותגים, מוצרים, ערים ושמות גיאוגרפיים. "
    "השתמש בלשון זכר רבים לתיאור פעילות החברה. "
    "אורך התרגום צריך להיות דומה למקור. "
    "החזר אך ורק את התרגום עצמו — בלי כותרת, הקדמה, הסבר או סוגריים."
)


def _load_cache() -> None:
    global _cache_loaded, _cache
    with _cache_lock:
        if _cache_loaded:
            return
        if CACHE_FILE.exists():
            try:
                _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if not isinstance(_cache, dict):
                    _cache = {}
            except Exception:
                _cache = {}
        _cache_loaded = True


def _save_cache() -> None:
    try:
        CACHE_FILE.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("translation cache save failed: %s", e)


def _hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


def translate_to_hebrew(text: str | None) -> str | None:
    """Translate English → Hebrew. Returns None if no API key or on error."""
    if not text or not text.strip():
        return None

    _load_cache()
    key = _hash(text)
    if key in _cache:
        return _cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None  # silent fallback — frontend shows English

    try:
        # Imported lazily so missing dependency doesn't crash the whole backend.
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": text}],
        )
        translated_parts = [
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ]
        translated = "".join(translated_parts).strip()
        if not translated:
            return None

        with _cache_lock:
            _cache[key] = translated
            _save_cache()
        return translated
    except Exception as e:
        log.warning("translate_to_hebrew failed: %s", e)
        return None
