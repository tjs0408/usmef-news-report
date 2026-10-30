"""Build an auditable, offline editorial corpus from the archived Ekape reports.

This is reference preparation, not model training. Historical quantities, dates,
and claims are never evidence for a newly selected reporting week. Extraction
quality and text cross-checking are recorded separately from factual verification.

Run from the repository root::

    python -m src.build_report_style_corpus

The input archive stays local. Only explicitly allow-listed public provenance is
copied to the generated application artifact; local paths are never serialized.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import unicodedata
from urllib.parse import urlsplit


CORPUS_VERSION = "ekape-2025plus-v1"
BOARD_URL = "https://www.ekapepia.com/v3/board/list.do?menuSn=28&boardInfoNo=0153"
KIND_ALIASES = {"domestic_beef": "domestic"}
KINDS = (
    "us", "australia", "domestic", "us_pork", "eu_pork", "domestic_pork",
    "us_chicken", "brazil_chicken", "domestic_chicken", "us_egg",
    "japan_egg", "domestic_egg",
)
THEMES = {
    "supply_statistic": r"생산량|도축량|도축두수|사육두수|재고량|부화기|입란|입식|공급|생산",
    "demand_consumption": r"수요|소비|판촉|바비큐|바베큐|외식|구매|선호|판매",
    "trade_access": r"수출|수입|관세|세이프가드|쿼터|검역|교역",
    "weather_disease": r"가뭄|강우|폭우|폭염|고온|더위|기후|기상|HPAI|조류인플루엔자|질병|구제역|ASF|살모넬라",
    "cost_logistics_margin": r"생산비|사료비|비용|수익|영업이익|운송|물류|배송|항공|근로|이민|결근",
    "policy_structure": r"규제|정책|행정|법안|협정|인증|유통|담합|법원|산업구조|법제|제도",
    "retail_inflation": r"CPI|물가|소비자가격|소매가격|식품가격",
    "price_direction": r"가격|시세|도매가|판매가|컷아웃",
}

# These are text-only, agent cross-checked paraphrases, not human-reviewed or
# independently fact-checked claims. Every entry must resolve to one original
# report paragraph. The source's quantity, comparator, uncertainty and causality
# are retained; no historical short text is padded just to satisfy current UI.
ADDITIONAL_REVIEWED = (
    ("us", "2025-12-25", "미국 내 1,000두 이상 비육장의 비육우는 전년비 2% 감소한 1,170만두, 11월 입식은 전년비 11% 감소한 160만두"),
    ("australia", "2025-12-18", "호주 소의 평균 도체중은 2022년 324kg에서 2025년 309kg으로 감소, 목초사육 및 암소 도축 증가 영향"),
    ("domestic", "2025-12-25", "한국은행 수입물가지수에 따르면 소고기 수입물가는 5년간 달러 기준 30%, 원화 기준 60.6% 상승"),
    ("us_pork", "2025-12-25", "미국 돼지고기 생산량이 전년비 많음에도 멕시코 수출 호조와 크리스마스 휴일 수요로 가격 상승"),
    ("eu_pork", "2025-11-27", "2024년 사료·에너지 비용 안정으로 생산비가 낮아져 돼지 가격 하락에도 농가 순이익에 미치는 영향은 미미"),
    ("domestic_pork", "2025-12-25", "한국은행에 따르면 수입 돼지고기 가격은 2020년 대비 달러 기준 6%, 원화 기준 31% 상승"),
    ("us_chicken", "2026-08-20", "미국의 주간 닭고기 생산량은 10억파운드(45.4만톤) 이상으로 안정, 도매가격 강세에도 소매 판촉률을 전주비 7.8%p 늘려 소비자 부담 완화"),
    ("us_chicken", "2026-09-17", "미국 육계용 계란 부화기 투입량은 고온으로 전주비 295만 9천개 감소한 2억 4572만 2천개, 산란계 사육 증가로 전년동기비 2% 증가"),
    ("domestic_chicken", "2026-09-17", "베트남의 가금육·부산물 수입 평균가격은 kg당 1달러에 불과해 채소 가격보다 낮은 수준"),
    ("us_egg", "2026-08-20", "산란계 공급 회복으로 계란 재고량이 증가하는 등 공급여건이 개선되며 도매·소매가격 하락"),
    ("japan_egg", "2026-09-17", "일본의 2026년 9월 7~9일 계란 가격은 10개당 309엔으로 전년의 101%, 평년의 119% 수준"),
    ("domestic_egg", "2026-08-27", "수입 달걀과 연관된 살모넬라균 감염이 늘면서 영국산 달걀 보증제도 인증 달걀 섭취 권고"),
)


def clean_text(value: Any) -> str:
    """Collapse extraction line wraps; do not infer Korean word spacing."""
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"^\s*[∙•·]\s*", "", text)
    text = re.sub(r"^\s*-\s*(?:\(현지동향\)\s*)?", "", text)
    text = re.sub(r"^\s*\(현지동향\)\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _valid_date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname.lower() not in {"ekapepia.com", "www.ekapepia.com"}:
        return None
    return value


def _provenance(record: dict[str, Any]) -> dict[str, Any]:
    """No arbitrary input metadata, filenames, paths, or credentials escape."""
    result = {
        "reportDate": _valid_date(record.get("report_date")),
        "page": record.get("page") if isinstance(record.get("page"), int) else None,
        "boardUrl": _public_url(record.get("detail_url")),
        "boardNo": str(record.get("board_no") or ""),
        "attachmentNo": str(record.get("attachment_no") or ""),
        "sourceAttachmentUrl": _public_url(record.get("source_download_url")),
    }
    return {key: value for key, value in result.items() if value is not None and value != ""}


def _id(kind: str, text: str, suffix: str = "") -> str:
    digest = hashlib.sha256(f"{kind}|{_compact(text)}|{suffix}".encode("utf-8")).hexdigest()[:16]
    return f"ekape-{digest}"


def _themes(text: str) -> list[str]:
    return [name for name, pattern in THEMES.items() if re.search(pattern, text, flags=re.I)] or ["other_market_context"]


def _fact_shape(text: str) -> str:
    if re.search(r"아니라|반면|에도|으나|지만", text):
        return "contrasting_conditions_or_offsetting_effects"
    if re.search(r"전망|예상|예측|우려|가능성|예정", text):
        return "condition_or_change_with_uncertain_outlook"
    if re.search(r"따라|인해|기인|영향|으로|여서|면서|에따른", _compact(text)):
        return "market_driver_and_consequence"
    if re.search(r"\d", text):
        return "market_indicator_with_comparison"
    return "qualitative_market_condition"


def _hard_exclusion(kind: str, text: str, title: str) -> str | None:
    combined = f"{title} {text}"
    if not text:
        return "empty_summary"
    if re.search(r"세포배양.?백신|계란.?변이|유정란.?적응.?변이", combined):
        return "non_food_egg_vaccine_topic"
    # A visibly repeated OCR line is not three separate report assertions.
    compact = _compact(text)
    if re.search(r"(.{15,}?)\s*(?:[-∙•]|…)?\s*\1", compact):
        return "repeated_extraction_fragment"
    if "pork" in kind and re.search(r"쇠고기|소고기|송아지", text) and not re.search(r"돼지|퇘지|돈육|양돈|[쇠소]고기대체", _compact(combined)):
        return "wrong_commodity_in_report_slot"
    if len(compact) < 5:
        return "insufficient_fragment"
    return None


def _quality_flags(record: dict[str, Any], text: str, kind: str) -> list[str]:
    flags = []
    if re.search(r"[가-힣]{14,}", text):
        flags.append("extracted_word_spacing_unreviewed")
    if len(text) < 40:
        flags.append("short_historical_style")
    if len(text) > 95:
        flags.append("long_historical_style")
    if record.get("date_mismatch") or record.get("board_title_date_mismatch"):
        flags.append("report_date_resolved_from_heading")
    # Do not repair contradictory comparison labels, suspicious scale or mixed
    # units. Retain them for coverage but keep them out of prompt exemplars.
    compact = _compact(text)
    if len(re.findall(r"전년[比비][^,;]{0,16}?[%]?[↓↑]", compact)) > 1 and "전년比1.5%↓,전년比2.0%↑" in compact:
        flags.append("conflicting_comparison_in_source")
    if "2,079만톤" in text and kind == "australia":
        flags.append("quantity_scale_needs_review")
    if "19억3천파운드" in compact:
        flags.append("quantity_unit_needs_review")
    if kind == "eu_pork" and "영국" in text and not re.search(r"독일|EU|유럽|스페인|프랑스|벨기에", text):
        flags.append("outside_current_eu_country_scope")
    if re.search(r"(?:했으|되었으|늘었으|것으로|위해|따라|때문에|그리고|반면)[,. ]*$", text):
        flags.append("possibly_unfinished_sentence")
    return flags


def _exclusion(record: dict[str, Any], kind: str, reason: str, text: str) -> dict[str, Any]:
    return {"id": _id(kind, text), "kind": kind, "reason": reason, "text": text, **_provenance(record)}


def build_corpus(
    local_records: Iterable[dict[str, Any]],
    domestic_records: Iterable[dict[str, Any]],
    analysis: dict[str, Any],
    coverage: dict[str, Any],
    reviewed_reference: dict[str, Any],
    *,
    min_year: int = 2025,
    additional_reviewed: Iterable[tuple[str, str, str]] = ADDITIONAL_REVIEWED,
) -> dict[str, Any]:
    """Prepare a deterministic artifact from already-extracted local records."""
    records = list(local_records) + list(domestic_records)
    scoped: list[dict[str, Any]] = []
    out_of_scope = Counter()
    exclusions: list[dict[str, Any]] = []
    by_paragraph: dict[tuple[str, str], dict[str, Any]] = {}
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in sorted(records, key=lambda item: (str(item.get("report_date", "")), str(item.get("key", ""))), reverse=True):
        kind = KIND_ALIASES.get(str(record.get("key")), str(record.get("key")))
        report_date = _valid_date(record.get("report_date"))
        if not report_date:
            out_of_scope["invalid_or_missing_report_date"] += 1
            continue
        if int(report_date[:4]) < min_year:
            out_of_scope["before_min_year"] += 1
            continue
        scoped.append(record)
        text = clean_text(record.get("paragraph"))
        title = clean_text(record.get("title")) if kind.startswith("domestic") else ""
        reason = "unknown_kind" if kind not in KINDS else _hard_exclusion(kind, text, title)
        provenance = _provenance(record)
        if not provenance.get("boardUrl") or not (provenance.get("sourceAttachmentUrl") or provenance.get("attachmentNo")):
            reason = reason or "missing_public_provenance"
        if reason:
            exclusions.append(_exclusion(record, kind, reason, text))
            continue
        lookup[(kind, report_date)].append(record)
        key = (kind, _compact(text))
        if key in by_paragraph:
            old = by_paragraph[key]
            if provenance not in old["duplicateProvenance"] and provenance != {k: old[k] for k in provenance if k in old}:
                old["duplicateProvenance"].append(provenance)
            old["occurrenceCount"] += 1
            continue
        flags = _quality_flags(record, text, kind)
        entry: dict[str, Any] = {
            "id": _id(kind, text), "kind": kind, "text": text,
            **provenance, "themes": _themes(text), "factShape": _fact_shape(text),
            "reviewStatus": "machine-extracted", "safeForPrompt": False,
            "qualityFlags": flags, "occurrenceCount": 1, "duplicateProvenance": [],
        }
        if title:
            entry["title"] = title
            if record.get("citation"):
                entry["citation"] = clean_text(record["citation"])
        by_paragraph[key] = entry

    examples = list(by_paragraph.values())
    reviewed_inputs = [dict(item) for item in reviewed_reference.get("examples", [])]
    reviewed_inputs += [{"kind": k, "reportDate": d, "text": t} for k, d, t in additional_reviewed]
    review_skips: list[dict[str, Any]] = []
    seen_reviewed = set()
    for item in reviewed_inputs:
        kind = KIND_ALIASES.get(str(item.get("kind")), str(item.get("kind")))
        report_date = _valid_date(item.get("reportDate"))
        text = clean_text(item.get("text"))
        if not report_date or int(report_date[:4]) < min_year:
            continue
        matches = lookup.get((kind, report_date), [])
        if item.get("boardNo"):
            matches = [m for m in matches if m.get("board_no") == item["boardNo"]]
        if item.get("page"):
            matches = [m for m in matches if m.get("page") == item["page"]]
        if len(matches) != 1:
            review_skips.append({"kind": kind, "reportDate": report_date, "reason": "ambiguous_or_unmatched_reviewed_source"})
            continue
        original = matches[0]
        original_text = clean_text(original["paragraph"])
        source_flags = _quality_flags(original, original_text, kind)
        if any(f.startswith(("conflicting_", "quantity_", "possibly_unfinished", "outside_current")) for f in source_flags):
            review_skips.append({"kind": kind, "reportDate": report_date, "reason": "source_quality_requires_review"})
            continue
        if _hard_exclusion(kind, text, clean_text(original.get("title"))) or len(text) < 40 or len(text) > 95:
            review_skips.append({"kind": kind, "reportDate": report_date, "reason": "reviewed_example_not_prompt_suitable"})
            continue
        key = (kind, _compact(text))
        if key in seen_reviewed:
            continue
        seen_reviewed.add(key)
        entry = {
            "id": _id(kind, text, "reviewed"), "kind": kind, "text": text,
            "originalText": original_text, "originalExampleId": _id(kind, original_text),
            **_provenance(original), "themes": _themes(text),
            "factShape": item.get("factShape") or _fact_shape(text),
            "reviewStatus": "reviewed-paraphrase", "reviewedBy": "agent-text-crosscheck",
            "reviewScope": "Original extracted paragraph and article title cross-check only; not visual or independent factual verification.",
            "safeForPrompt": True, "qualityFlags": [], "occurrenceCount": 1,
            "duplicateProvenance": [],
        }
        if item.get("theme") and item["theme"] not in entry["themes"]:
            entry["themes"].append(item["theme"])
        if kind.startswith("domestic"):
            entry["title"] = clean_text(original.get("title"))
            if original.get("citation"):
                entry["citation"] = clean_text(original["citation"])
        examples.append(entry)

    examples.sort(key=lambda item: (item["reportDate"], item["kind"], item["reviewStatus"], item["id"]), reverse=True)
    exclusions.sort(key=lambda item: (item.get("reportDate", ""), item["kind"], item["id"]), reverse=True)
    reports = list(analysis.get("reports", [])) + list(analysis.get("legacy_hwp_reports", []))
    report_provenance = {}
    unparsed_blocks = []
    for report in reports:
        report_date = _valid_date(report.get("report_date"))
        if report_date and int(report_date[:4]) >= min_year:
            provenance = _provenance(report)
            report_provenance[(provenance.get("boardNo"), provenance.get("attachmentNo"))] = provenance
            for block in report.get("unparsed_domestic_blocks", []):
                kind = KIND_ALIASES.get(str(block.get("key")), str(block.get("key")))
                raw_text = clean_text(block.get("raw_block"))
                unparsed_blocks.append({
                    "id": _id(kind, raw_text, "unparsed"), "kind": kind,
                    "rawText": raw_text, "reason": "incomplete_or_nonstandard_domestic_title_citation",
                    "safeForPrompt": False, **_provenance(block),
                })
    dates = sorted(p["reportDate"] for p in report_provenance.values())
    retained_raw = [item for item in examples if item["reviewStatus"] == "machine-extracted"]
    reviewed = [item for item in examples if item["safeForPrompt"]]
    by_kind = {}
    for kind in KINDS:
        kind_raw = [item for item in retained_raw if item["kind"] == kind]
        by_kind[kind] = {
            "retainedParagraphs": len(kind_raw),
            "sourceOccurrences": sum(item["occurrenceCount"] for item in kind_raw),
            "reviewedPromptExamples": sum(item["kind"] == kind for item in reviewed),
            "themes": dict(sorted(Counter(theme for item in kind_raw for theme in item["themes"]).items())),
        }
    return {
        "historicalStyleOnly": True, "corpusVersion": CORPUS_VERSION, "minYear": min_year,
        "boardUrl": BOARD_URL,
        "usage": {
            "purpose": "Historical editorial wording, topic selection and cause/consequence patterns only.",
            "notEvidenceForCurrentWeek": True, "modelWeightsTrained": False,
            "safeForPromptMeaning": "Agent text-crosschecked stylistic paraphrase, not a current fact or independently verified fact.",
            "preserveConditions": "Keep source uncertainty, negation, country, commodity, comparison periods and number units; never borrow historical facts for a new week.",
        },
        "scope": {
            "dateBasis": "report_date resolved by archive extractor; report heading wins over mismatched filename/board title",
            "firstReportDate": dates[0] if dates else None, "lastReportDate": dates[-1] if dates else None,
            "reportCount": len(report_provenance),
            "reportsByYear": dict(sorted(Counter(p["reportDate"][:4] for p in report_provenance.values()).items())),
            "inputRecordCount": len(records), "scopedRecordCount": len(scoped),
            "scopedRecordsByYear": dict(sorted(Counter(str(r["report_date"])[:4] for r in scoped).items())),
            "retainedParagraphCount": len(retained_raw),
            "retainedOccurrenceCount": sum(x["occurrenceCount"] for x in retained_raw),
            "duplicateParagraphOccurrenceCount": sum(x["occurrenceCount"] - 1 for x in retained_raw),
            "excludedRecordCount": len(exclusions),
            "exclusionReasons": dict(sorted(Counter(x["reason"] for x in exclusions).items())),
            "outOfScopeReasons": dict(sorted(out_of_scope.items())),
            "reviewedPromptExampleCount": len(reviewed),
            "reviewedExamplesByYear": dict(sorted(Counter(x["reportDate"][:4] for x in reviewed).items())),
            "exampleCount": len(examples), "byKind": by_kind,
            "unparsedDomesticBlockCount": len(unparsed_blocks),
        },
        "archiveCoverage": {
            "declaredBoardTotal": analysis.get("declared_board_total"),
            "archiveTextExtractedReports": analysis.get("reports_extracted"),
            "unparsedDomesticBlockCountAllYears": analysis.get("unparsed_domestic_block_count"),
            "archiveCompletedAtUtc": coverage.get("completed_at_utc"),
            "emptyOrImageOnlyPdfCountAllYears": coverage.get("image_only_or_empty_pdf_count"),
            "downloadOrParseErrorCountAllYears": len(coverage.get("attachment_download_or_parse_errors", [])),
            "limitations": [
                "All in-scope extracted records were processed; not every PDF page has been individually visually reviewed.",
                "Unparsed domestic blocks are not silently converted into examples or attributed to invented publishers.",
                "A publisher/title/date citation is not proof that the adjacent table source authored that summary.",
                "Machine-extracted spacing and suspicious quantities are retained with quality flags, never silently corrected.",
                "2025 poultry and egg coverage begins only at the late-December expanded report format; earlier missing sections are not invented.",
            ],
        },
        "reports": sorted(report_provenance.values(), key=lambda p: (p["reportDate"], p.get("boardNo", "")), reverse=True),
        "examples": examples, "exclusions": exclusions, "reviewedExampleSkips": review_skips,
        "unparsedDomesticBlocks": unparsed_blocks,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=root / "work" / "ekape_archive")
    parser.add_argument("--reference", type=Path, default=root / "report_template" / "article_editorial_examples.json")
    parser.add_argument("--output", type=Path, default=root / "report_template" / "report_style_corpus_2025plus.json")
    parser.add_argument("--min-year", type=int, default=2025)
    args = parser.parse_args(argv)
    corpus = build_corpus(
        _read_json(args.archive_dir / "local_summary_records.json"),
        _read_json(args.archive_dir / "domestic_article_records.json"),
        _read_json(args.archive_dir / "report_analysis.json"),
        _read_json(args.archive_dir / "coverage.json"),
        _read_json(args.reference), min_year=args.min_year,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = corpus["scope"]
    print(f"reports={scope['reportCount']} retained={scope['retainedParagraphCount']} "
          f"excluded={scope['excludedRecordCount']} reviewed={scope['reviewedPromptExampleCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
