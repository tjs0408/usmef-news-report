"""Retrieve historical editorial structure, never historical market facts.

The small CPU model previously copied figures/events from full few-shot texts.
We therefore distil ONE topic-matched, text-crosschecked example into a clause
order. The archived sentence stays local/auditable; neither it nor its figures
is put in the generation prompt. Loading and retrieval require no network/AI.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re


CORPUS_PATH = Path(__file__).resolve().parents[1] / 'report_template/report_style_corpus_2025plus.json'
CORPUS_VERSION = 'ekape-2025plus-v1'
_KINDS = frozenset(('us', 'australia', 'domestic', 'us_pork', 'eu_pork', 'domestic_pork',
                    'us_chicken', 'brazil_chicken', 'domestic_chicken', 'us_egg', 'japan_egg', 'domestic_egg'))
_THEMES = {
    'supply_statistic': r'공급|생산|도축|사육|입식|입란|산란|재고|\b(?:supply|production|slaughter|herd|placements?|sets|inventory|layers?)\b|produ[çc]|abate|生産|供給|飼養',
    'demand_consumption': r'수요|소비|외식|구매|판매|\b(?:demand|consumption|sales|buying|grilling)\b|consumo|需要|消費',
    'trade_access': r'수출|수입|관세|교역|쿼터|검역|\b(?:exports?|imports?|tariffs?|quotas?|trade|duties)\b|exporta|importa|輸出|輸入|関税',
    'weather_disease': r'가뭄|폭염|기후|강우|질병|조류인플루엔자|\b(?:drought|heat|rain|flu|disease|HPAI|ASF)\b|gripe|猛暑|鳥インフル',
    'cost_logistics_margin': r'비용|사료비|수익|물류|운송|인력|이민|근로|\b(?:cost|costs|feed|margin|transport|logistics|labor|labour|immigration)\b',
    'policy_structure': r'규제|정책|법안|인증|유통|협정|\b(?:policy|regulation|agreement|approval|certification)\b|規制',
    'retail_inflation': r'물가|소비자가격|소매가격|\b(?:CPI|inflation|retail|consumer\s+prices?)\b|物価',
    'price_direction': r'가격|시세|도매가|컷아웃|\b(?:prices?|cutout|wholesale)\b|pre[çc]o|価格|相場',
}
_CAUSE = re.compile(r'때문|영향|여파|에\s*따[라른]|으로\s*인해|로\s*인해|(?:수요|공급|생산|도축|비용|사료비|운송|폭염|가뭄).{0,12}로\s|\b(?:because|due\s+to|driven\s+by|owing\s+to)\b|devido|により|ため', re.I)
_CONTRAST = re.compile(r'반면|에도|으나|지만|\b(?:while|whereas|despite|although|but)\b|一方', re.I)
_OUTLOOK = re.compile(r'전망|예상|가능성|우려|예정|계획|\b(?:forecast|expect|outlook|could|may|plan|risk)\w*\b|見通し|予測|previs', re.I)


@lru_cache(maxsize=1)
def style_corpus() -> dict:
    try:
        if CORPUS_PATH.stat().st_size > 1_500_000:
            return {}
        value = json.loads(CORPUS_PATH.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('historicalStyleOnly') is not True
                or value.get('corpusVersion') != CORPUS_VERSION or value.get('minYear') != 2025):
            return {}
        return value
    except (OSError, ValueError, TypeError):
        return {}


@lru_cache(maxsize=12)
def _reviewed_examples(kind: str) -> tuple[dict, ...]:
    examples = []
    for item in style_corpus().get('examples', []):
        if (not isinstance(item, dict) or item.get('kind') != kind or kind not in _KINDS
                or item.get('safeForPrompt') is not True or item.get('qualityFlags')
                or item.get('reviewStatus') != 'reviewed-paraphrase'
                or item.get('reviewedBy') != 'agent-text-crosscheck'
                or not isinstance(item.get('text'), str) or not 40 <= len(item['text']) <= 95
                or not str(item.get('boardUrl', '')).startswith('https://www.ekapepia.com/')
                or not item.get('originalText') or not item.get('id')):
            continue
        try:
            if date.fromisoformat(item['reportDate']).year < 2025:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        examples.append(item)
    return tuple(examples)


def _themes(context: str) -> frozenset[str]:
    return frozenset(theme for theme, pattern in _THEMES.items() if re.search(pattern, context, re.I))


def reference_for_source(kind: str, context: str) -> dict | None:
    """One same-section exemplar; no generic other-species fallback."""
    if not context.strip() or kind not in _KINDS:
        return None
    themes = _themes(context)
    if not themes:
        return None
    def shape(text):
        # Older examples used free-text factShape labels. Compare source and
        # example syntax consistently, not incompatible metadata labels.
        return (bool(_CONTRAST.search(text)), bool(_CAUSE.search(text)), bool(_OUTLOOK.search(text)))
    source_shape = shape(context)
    candidates = [item for item in _reviewed_examples(kind) if themes.intersection(item.get('themes', []))]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (
        len(themes.intersection(item.get('themes', []))) * 3
        + 3 * sum(a and b for a, b in zip(source_shape, shape(item['text']))),
        -len(set(item.get('themes', [])) - themes), item['reportDate'], item['id']))


def source_style_guidance(kind: str, context: str) -> tuple[str, dict | None]:
    """Distil an exemplar's syntax only if the current source licenses it.

    The actual old quote (even masked numbers) is deliberately NOT returned in
    the prompt. A historical cause, forecast or country cannot become evidence.
    """
    item = reference_for_source(kind, context)
    if item is None:
        return '', None
    sample = item['text']
    if _CONTRAST.search(sample) and _CONTRAST.search(context):
        order = '시장 여건·변화 → 반면/에도 다른 변화의 대비'
        pattern = 'contrast'
    elif _CAUSE.search(sample) and _CAUSE.search(context):
        order = '원문에 명시된 시장 배경·원인 → 해당 축종의 변화·영향'
        pattern = 'cause_and_change'
    elif _OUTLOOK.search(sample) and _OUTLOOK.search(context):
        order = '현재 시장 변화 → 원문이 제시한 조건부 전망'
        pattern = 'conditional_outlook'
    else:
        order = '대상 국가·축종 → 비교기간을 붙인 핵심 변화'
        pattern = 'market_change'
    guidance = (f'기존 보고서 문장 구성: {order}. '
                '기관 소개·나열보다 핵심 시장 사실 우선. 배경·대비가 원문에 없으면 추가하지 않음.')
    reference = {key: item[key] for key in ('id', 'kind', 'reportDate', 'page', 'boardUrl', 'reviewStatus') if key in item}
    reference.update(corpusVersion=CORPUS_VERSION, mode='retrieved_structure_only', pattern=pattern)
    return guidance, reference
