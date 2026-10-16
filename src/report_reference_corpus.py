"""Reviewed historical style/source metadata; never evidence for a new week.

The archive is analyzed offline. Report generation reads this small local file
only, not hundreds of historical PDFs or a user's Downloads directory.
"""
from datetime import date
from functools import lru_cache
import json
from pathlib import Path


REFERENCE_PATH = Path(__file__).resolve().parents[1] / 'report_template/article_editorial_examples.json'


@lru_cache(maxsize=1)
def editorial_reference() -> dict:
    try:
        if REFERENCE_PATH.stat().st_size > 250_000:
            return {}
        value = json.loads(REFERENCE_PATH.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) and value.get('historicalStyleOnly') is True else {}
    except (OSError, ValueError):
        return {}


def historical_style_examples(kind: str) -> tuple[str, ...]:
    result = []
    for item in editorial_reference().get('examples', []):
        if not isinstance(item, dict) or item.get('kind') != kind:
            continue
        text = item.get('text')
        if (isinstance(text, str) and 40 <= len(text) <= 95
                and isinstance(item.get('page'), int) and item['page'] > 0):
            try:
                date.fromisoformat(item.get('reportDate', ''))
            except (ValueError, TypeError):
                continue
            if text not in result:
                result.append(text)
    return tuple(result)


def cited_media_names(kind: str) -> tuple[str, ...]:
    """Discovery seeds, not a publisher whitelist or a source-date assertion."""
    if kind != 'domestic' and not kind.startswith('domestic_'):
        return ()
    same_species, other_media = [], []
    for item in editorial_reference().get('sources', []):
        if not isinstance(item, dict) or item.get('role') != 'article-search':
            continue
        name = item.get('name')
        kinds = item.get('kind', [])
        if (not isinstance(name, str) or not 2 <= len(name) <= 35
                or any(token in name for token in ('\n', '\r', '<', '>', '"'))
                or not isinstance(kinds, list) or not any(str(key).startswith('domestic') for key in kinds)
                or not item.get('citationEvidence')):
            continue
        # An outlet used previously for beef can also cover poultry or eggs.
        group = same_species if kind in kinds else other_media
        if name not in same_species + other_media:
            group.append(name)
    return tuple(same_species + other_media)


def cited_media_queries(kind: str, week_start: date, *, limit: int = 2) -> tuple[str, ...]:
    """At most two rotating outlet queries after broad, unrestricted searches."""
    names = cited_media_names(kind)
    commodity = {'domestic': '소고기', 'domestic_pork': '돼지고기',
                 'domestic_chicken': '닭고기', 'domestic_egg': '계란'}.get(kind)
    if not names or commodity is None or limit <= 0:
        return ()
    offset = (week_start.toordinal() // 7) % len(names)
    return tuple(f'{commodity} 해외 {names[(offset + step) % len(names)]}'
                 for step in range(min(limit, 2, len(names))))
