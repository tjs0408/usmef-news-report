"""Content-addressed local cache for expensive public USMEF PDF text/OCR.

The caller downloads the original first. Neither a URL nor the selected report
date can reuse text from changed PDF bytes. This is original text, not a saved
summary, and normal publication/species/summary validation still follows.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile


CACHE_DIR = Path(__file__).resolve().parents[1] / 'output' / 'article_source_cache'
EXTRACTOR_VERSION = 'usmef-heading-sections-v1'


def _key(document: bytes) -> str:
    return sha256(EXTRACTOR_VERSION.encode() + b'\0' + document).hexdigest()


def _valid(texts) -> bool:
    return (isinstance(texts, dict) and bool(texts)
            and set(texts) == {'beef', 'pork'}
            and all(isinstance(value, str) and 120 <= len(value) <= 6000 for value in texts.values()))


def load_source_text(document: bytes) -> dict[str, str] | None:
    if not document.startswith(b'%PDF-'):
        return None
    key = _key(document)
    try:
        path = CACHE_DIR / (key + '.json')
        if path.stat().st_size > 100_000:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None
    if (not isinstance(value, dict) or value.get('key') != key
            or value.get('extractorVersion') != EXTRACTOR_VERSION or not _valid(value.get('texts'))):
        return None
    return dict(value['texts'])


def save_source_text(document: bytes, texts: dict[str, str]) -> None:
    if not document.startswith(b'%PDF-') or not _valid(texts):
        return
    key = _key(document)
    temporary = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.tmp',
                                         prefix=key + '-', dir=CACHE_DIR, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'key': key, 'extractorVersion': EXTRACTOR_VERSION, 'texts': texts},
                      stream, ensure_ascii=False)
        os.replace(temporary, CACHE_DIR / (key + '.json'))
    except OSError:
        # A read-only cache or disk error must not invalidate a parsed source.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
