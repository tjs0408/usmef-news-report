import json
from pathlib import Path
import tempfile
import unittest

from src.build_report_style_corpus import build_corpus, clean_text, main


def record(text, *, kind="us", report_date="2025-03-06", board="001", page=1, **extra):
    return {
        "key": kind, "paragraph": text, "report_date": report_date,
        "board_no": board, "attachment_no": f"a{board}", "page": page,
        "detail_url": f"https://www.ekapepia.com/v3/board/detail.do?boardNo={board}",
        "source_download_url": f"https://www.ekapepia.com/common/attachfile/attachfileDownload.do?attachNo=a{board}",
        "source_file": r"C:\private\user\secrets\local.pdf", **extra,
    }


def build(local=(), domestic=(), reviewed=None, reports=(), **kwargs):
    return build_corpus(local, domestic, {"reports": list(reports)}, {}, reviewed or {}, additional_reviewed=(), **kwargs)


def test_strict_report_year_and_heading_basis_not_registration_year():
    current = record("공급 감소에 따른 수출 가격 상승", registered_date="2024-12-31")
    old = record("과거 생산량 증가", report_date="2024-12-26", registered_date="2025-01-01")
    missing = record("날짜 없는 단편", report_date="2025-13-01")
    result = build([current, old, missing], reports=[current, old])
    assert result["scope"]["scopedRecordCount"] == 1
    assert result["scope"]["reportsByYear"] == {"2025": 1}
    assert result["scope"]["outOfScopeReasons"] == {"before_min_year": 1, "invalid_or_missing_report_date": 1}


def test_public_provenance_allowlist_does_not_leak_local_paths_or_extra_data():
    source = record("생산량 감소에 따라 가격 강세 유지", client_secret="do-not-copy", filename="private.pdf")
    result = build([source], reports=[source])
    serialized = json.dumps(result)
    assert "private" not in serialized
    assert "client_secret" not in serialized
    assert "do-not-copy" not in serialized
    assert result["examples"][0]["sourceAttachmentUrl"].startswith("https://www.ekapepia.com/")
    assert result["examples"][0]["attachmentNo"] == "a001"


def test_missing_or_credential_bearing_provenance_is_excluded():
    source = record("생산량 감소에 따른 가격 상승", detail_url="https://secret:password@www.ekapepia.com/x")
    result = build([source])
    assert result["examples"] == []
    assert result["exclusions"][0]["reason"] == "missing_public_provenance"
    assert "password" not in json.dumps(result)


def test_actual_paragraph_dedup_ignores_extraction_spaces_not_species():
    sources = [
        record("공급 증가에 따른 가격 하락", board="1"),
        record("공급증가에따른가격하락", board="2", report_date="2026-03-05"),
        record("공급 증가에 따른 가격 하락", kind="us_pork", board="3"),
    ]
    result = build(sources)
    assert result["scope"]["retainedParagraphCount"] == 2
    assert result["scope"]["retainedOccurrenceCount"] == 3
    assert result["scope"]["duplicateParagraphOccurrenceCount"] == 1
    beef = next(x for x in result["examples"] if x["kind"] == "us")
    assert beef["reportDate"] == "2026-03-05"
    assert beef["duplicateProvenance"][0]["boardNo"] == "1"
    assert beef["occurrenceCount"] == 2


def test_incomplete_nonmarket_and_wrong_slot_separate_from_valid_substitution():
    bad = [
        record("유정란 적응 변이 차단 및 예방효과 입증", kind="domestic_egg", title="계란 변이 없는 세포배양 백신"),
        record("영국 통계청, 쇠고기 및 송아지 가격 상승 둔화", kind="eu_pork"),
        record("긴 반복 추출문장입니다아무의미없습니다 - 긴 반복 추출문장입니다아무의미없습니다", kind="domestic_pork"),
    ]
    good = [
        record("공급은 증가하고 있으나 수출 수요와 쇠고기 대체 수요 증가가 가격 지지", kind="us_pork"),
        record("암퇘지 허벅지살을 가짜 소고기로 재판매한 일당 체포", kind="domestic_pork"),
        record("수출은 증가했으나", kind="us"),
    ]
    result = build(bad + good)
    assert len(result["exclusions"]) == 3
    assert len(result["examples"]) == 3
    unfinished = next(x for x in result["examples"] if x["text"] == "수출은 증가했으나")
    assert not unfinished["safeForPrompt"]
    # A retained short historical phrase is not padded into a model exemplar.
    assert "short_historical_style" in unfinished["qualityFlags"]


def test_domestic_title_is_separate_summary_prefix_removed_and_partial_metadata_supported():
    source = record("- (현지동향) 수입 감소로 가격 상승 우려", kind="domestic_beef", title="제목", citation="언론사, 3.1.", page=None)
    result = build(domestic=[source])
    example = result["examples"][0]
    assert example["kind"] == "domestic"
    assert example["text"] == "수입 감소로 가격 상승 우려"
    assert example["title"] == "제목"
    assert example["citation"] == "언론사, 3.1."
    assert "page" not in example


def test_unparsed_partial_domestic_format_is_preserved_without_invented_citation():
    source = record("", kind="domestic_egg")
    block = {**source, "raw_block": "∙불완전한 제목\n- 항공기로 계란 수송"}
    report = {**source, "unparsed_domestic_blocks": [block]}
    result = build(reports=[report])
    assert result["scope"]["unparsedDomesticBlockCount"] == 1
    preserved = result["unparsedDomesticBlocks"][0]
    assert preserved["safeForPrompt"] is False
    assert "publisher" not in preserved and "citation" not in preserved
    assert "항공기로 계란 수송" in preserved["rawText"]
    assert "source_file" not in json.dumps(preserved)


def test_crosschecked_paraphrase_requires_exact_public_original_and_retains_qualifiers():
    original = "소고기가격상승으로번식우농가는혜택을받는반면비육농가는비용압박"
    reference = {
        "examples": [{
            "kind": "us", "reportDate": "2025-03-06", "page": 1,
            "text": "소고기 가격 상승으로 번식우 농가는 높은 판매가격의 혜택을 받는 반면 비육농가는 비용 압박",
        }]
    }
    result = build([record(original)], reviewed=reference)
    reviewed = next(x for x in result["examples"] if x["safeForPrompt"])
    assert reviewed["reviewStatus"] == "reviewed-paraphrase"
    assert reviewed["reviewedBy"] == "agent-text-crosscheck"
    assert reviewed["originalText"] == original
    assert reviewed["originalExampleId"] in {x["id"] for x in result["examples"]}
    assert "반면" in reviewed["text"]
    assert result["historicalStyleOnly"]
    assert result["usage"]["notEvidenceForCurrentWeek"]
    assert not result["usage"]["modelWeightsTrained"]
    unmatched = build([], reviewed=reference)
    assert unmatched["scope"]["reviewedPromptExampleCount"] == 0
    assert unmatched["reviewedExampleSkips"][0]["reason"] == "ambiguous_or_unmatched_reviewed_source"


def test_cli_is_offline_and_reproducible_for_partial_archive():
    with tempfile.TemporaryDirectory() as temporary:
        tmp_path = Path(temporary)
        archive = tmp_path / "archive"
        archive.mkdir()
        source = record("생산량 증가에도 수요가 유지되어 가격 하락 제한")
        for filename, data in [
            ("local_summary_records.json", [source]), ("domestic_article_records.json", []),
            ("report_analysis.json", {"reports": [source]}), ("coverage.json", {}),
        ]:
            (archive / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        reference = tmp_path / "reference.json"
        reference.write_text("{}", encoding="utf-8")
        output = tmp_path / "corpus.json"
        args = ["--archive-dir", str(archive), "--reference", str(reference), "--output", str(output)]
        assert main(args) == 0
        first = output.read_bytes()
        assert main(args) == 0
        assert output.read_bytes() == first
        assert str(tmp_path) not in first.decode("utf-8")


def test_checked_in_corpus_is_auditable_and_covers_all_twelve_kinds():
    path = Path(__file__).resolve().parents[1] / "report_template" / "report_style_corpus_2025plus.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    safe = [x for x in corpus["examples"] if x["safeForPrompt"]]
    assert len({x["kind"] for x in safe}) == 12
    assert all(x["reportDate"] >= "2025-01-01" for x in corpus["examples"])
    assert len({(x["kind"], "".join(x["text"].split()), x["reviewStatus"]) for x in corpus["examples"]}) == len(corpus["examples"])
    assert all(x.get("boardUrl") and x.get("sourceAttachmentUrl") for x in corpus["examples"])
    assert corpus["scope"]["retainedOccurrenceCount"] + corpus["scope"]["excludedRecordCount"] == corpus["scope"]["scopedRecordCount"]
    assert all(40 <= len(x["text"]) <= 95 and x.get("originalText") for x in safe)
    assert {x["reportDate"][:4] for x in safe} == {"2025", "2026"}
    chicken = [x for x in safe if x["kind"] == "us_chicken"]
    assert sum("supply_statistic" in x["themes"] for x in chicken) >= 2
    assert any("전년동기비 2%" in x["text"] and "전주비" in x["text"] for x in chicken)
    assert "C:\\" not in path.read_text(encoding="utf-8")


def test_clean_text_does_not_delete_qualifiers_negation_or_change_numbers():
    assert clean_text("- (현지동향) 생산 부족이 아니라 비용 악화로 도축 감소 우려\n전년비 3%") == "생산 부족이 아니라 비용 악화로 도축 감소 우려 전년비 3%"


def load_tests(loader, tests, pattern):
    """Run dependency-free fixtures under this project's unittest runner."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
