"""USMEF Korea 뉴스라인 PDF에서 소고기 주간 지표를 수집합니다."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any, Callable
from urllib.request import Request, urlopen

import pymupdf
from bs4 import BeautifulSoup
from rapidocr import ModelType, OCRVersion, RapidOCR


NEWSLINE_URL = "https://www.usmef.co.kr/main/newsline.php"
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "USMEF-Weekly-Market-Report/1.0 (+https://github.com/tjs0408/usmef-news-report)"


def fetch_first_page_market_data() -> list[dict[str, object]]:
    """뉴스라인 1페이지 전체의 소고기 컷아웃·도축두수를 반환합니다.

    USMEF Korea의 뉴스라인은 이미지 기반 PDF로 제공됩니다. 따라서 최신 PDF의
    첫 페이지를 고해상도로 렌더링한 뒤, 한국어 OCR로 필요한 값만 읽습니다.
    """
    entries = _find_first_page_pdf_entries(_download_text(NEWSLINE_URL))
    return _fetch_market_data_from_entries(entries)


def fetch_market_data_for_report_dates(
    report_dates: set[date],
    progress_callback: Callable[[int, int, date], None] | None = None,
) -> list[dict[str, object]]:
    """지정한 발행일의 뉴스라인 PDF에서 소고기 지표를 수집합니다.

    엑셀의 금요일 주차 행은 다음 주 수요일에 발행된 뉴스라인과 연결됩니다.
    필요한 행만 채울 때에는 전체 첫 페이지를 OCR 처리하지 않도록 이 함수를 씁니다.
    """
    entries = [
        entry
        for entry in _find_first_page_pdf_entries(_download_text(NEWSLINE_URL))
        if entry[0].date() in report_dates
    ]
    missing_dates = sorted(report_dates - {report_date.date() for report_date, _ in entries})
    if missing_dates:
        missing_text = ", ".join(report_date.isoformat() for report_date in missing_dates)
        raise RuntimeError(f"뉴스라인 1페이지에서 요청한 발행일을 찾지 못했습니다: {missing_text}")
    return _fetch_market_data_from_entries(entries, progress_callback)


def _fetch_market_data_from_entries(
    entries: list[tuple[datetime, str]],
    progress_callback: Callable[[int, int, date], None] | None = None,
) -> list[dict[str, object]]:
    market_data: list[dict[str, object]] = []
    failures: list[str] = []

    for index, (report_date, pdf_url) in enumerate(entries, start=1):
        if progress_callback is not None:
            progress_callback(index, len(entries), report_date.date())
        try:
            market_data.append(_extract_market_data(pdf_url, report_date))
        except RuntimeError as error:
            failures.append(f"{report_date:%Y-%m-%d}: {error}")

    if failures:
        details = "\n".join(failures)
        raise RuntimeError(f"뉴스라인 {len(failures)}건을 읽지 못했습니다.\n{details}")
    return market_data


def fetch_latest_market_data() -> dict[str, object]:
    """하위 호환용으로 최신 뉴스라인 한 건을 반환합니다."""
    return fetch_first_page_market_data()[0]


def _extract_market_data(pdf_url: str, report_date: datetime) -> dict[str, object]:
    ocr_lines, page_width, page_height = _read_pdf_with_ocr(_download_bytes(pdf_url))

    return {
        "구분": report_date.date(),
        "도축두수": _find_beef_slaughter_count(ocr_lines, page_width, page_height),
        "usda 수정": _find_beef_previous_slaughter_count(ocr_lines, page_width, page_height),
        "미국($/lb)": _find_beef_cutout_price(ocr_lines, page_width, page_height),
        "돼지 도축두수": _find_pork_slaughter_count(ocr_lines, page_width, page_height),
        "돼지 usda 수정": _find_pork_previous_slaughter_count(ocr_lines, page_width, page_height),
        "돼지 미국($/lb)": _find_pork_cutout_price(ocr_lines, page_width, page_height),
    }


def _download_text(url: str) -> str:
    return _download_bytes(url).decode("utf-8", errors="replace")


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise RuntimeError("USMEF 서버에서 뉴스라인 파일을 가져오지 못했습니다.") from error


def _find_first_page_pdf_entries(html: str) -> list[tuple[datetime, str]]:
    """뉴스라인 목록 1페이지의 PDF와 발행일을 최신순으로 가져옵니다."""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("a.board_content")
    if not links:
        raise RuntimeError("USMEF 뉴스라인의 최신 게시물을 찾지 못했습니다.")

    entries: list[tuple[datetime, str]] = []
    for link in links:
        onclick = link.get("href", "")
        match = re.search(r"sampleOpenWin\('([^']+\.pdf)'", onclick, flags=re.IGNORECASE)
        if match is None:
            continue
        pdf_url = match.group(1)
        entries.append((_date_from_pdf_url(pdf_url), pdf_url))

    if not entries:
        raise RuntimeError("뉴스라인 1페이지에서 PDF 주소를 읽지 못했습니다.")
    return sorted(entries, key=lambda entry: entry[0], reverse=True)


def _date_from_pdf_url(pdf_url: str) -> datetime:
    """뉴스라인 PDF 경로의 YYYYMMDD 발행일을 날짜로 변환합니다."""
    match = re.search(r"/(\d{8})/[^/]+\.pdf$", pdf_url)
    if match is None:
        raise RuntimeError("뉴스라인 PDF 주소에서 발행일을 읽지 못했습니다.")
    return datetime.strptime(match.group(1), "%Y%m%d")


@lru_cache(maxsize=1)
def _get_ocr() -> RapidOCR:
    """한국어와 숫자를 인식하는 경량 OCR 엔진을 한 번만 준비합니다."""
    return RapidOCR(
        params={
            "Rec.lang_type": "korean",
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }
    )


def _read_pdf_with_ocr(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], float, float]:
    """PDF 첫 페이지의 오른쪽 요약 카드를 나눠 OCR 문장과 좌표를 추출합니다."""
    document = None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page = document[0]
        page_width = float(page.rect.width * 2 * 0.45)
        page_height = float(page.rect.height * 2 * 0.45)
    except Exception as error:
        raise RuntimeError("뉴스라인 PDF를 읽을 수 없습니다.") from error

    try:
        lines: list[dict[str, Any]] = []
        # 카드의 세로 위치가 호마다 달라서 상단 45%를 여러 조각으로 읽는다. 첫 번째
        # 컷아웃/도축두수 카드는 소고기, 그 뒤 카드는 돼지고기다.
        segment_ratio = 0.12
        with TemporaryDirectory() as temporary_directory:
            for segment_index, start_ratio in enumerate((0.0, 0.12, 0.24, 0.36, 0.48)):
                crop = pymupdf.Rect(
                    page.rect.width * 0.55,
                    page.rect.height * start_ratio,
                    page.rect.width,
                    page.rect.height * min(start_ratio + segment_ratio, 0.60),
                )
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=crop, alpha=False)
                image_path = Path(temporary_directory) / f"newsline_{segment_index}.png"
                image_path.write_bytes(pixmap.tobytes("png"))
                # 뉴스라인은 정방향 PDF이므로 방향 분류 추론은 생략해 OCR 시간을 줄인다.
                result = _get_ocr()(str(image_path), use_cls=False)
                if not result.txts or result.boxes is None:
                    continue
                y_offset = float(crop.y0 * 2)
                for text, box in zip(result.txts, result.boxes, strict=True):
                    lines.append(
                        {
                            "text": text,
                            "left": float(min(point[0] for point in box)),
                            "top": float(min(point[1] for point in box)) + y_offset,
                        }
                    )
    except Exception as error:
        raise RuntimeError(f"뉴스라인의 숫자를 읽는 OCR 처리에 실패했습니다. ({error})") from error
    finally:
        if document is not None:
            document.close()

    if not lines:
        raise RuntimeError("뉴스라인에서 읽을 수 있는 텍스트를 찾지 못했습니다.")
    return lines, page_width, page_height


def _find_beef_cutout_price(lines: list[dict[str, Any]], page_width: float, page_height: float) -> float:
    return _find_cutout_price(lines, occurrence=0, market_name="소고기")


def _find_pork_cutout_price(lines: list[dict[str, Any]], page_width: float, page_height: float) -> float:
    return _find_cutout_price(lines, occurrence=1, market_name="돼지고기")


def _find_cutout_price(lines: list[dict[str, Any]], occurrence: int, market_name: str) -> float:
    cutout_label = (
        _find_pork_label(lines, "컷아웃", f"{market_name} 컷아웃")
        if market_name == "돼지고기"
        else _find_label(lines, "컷아웃", occurrence, f"{market_name} 컷아웃")
    )
    candidates = sorted(
        (line for line in lines if cutout_label["top"] - 80 <= line["top"] <= cutout_label["top"] + 750),
        key=lambda line: line["top"],
    )
    if market_name == "돼지고기":
        # 돼지고기 카드에서는 '$'와 현재 가격을 서로 다른 상자로 읽는 경우가 많다.
        for line in candidates:
            if not (cutout_label["left"] - 30 <= line["left"] <= cutout_label["left"] + 350):
                continue
            match = re.fullmatch(r"\s*([01]\.\d{2})\s*", line["text"])
            if match:
                return float(match.group(1))

    price_pattern = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
    for line in candidates:
        if not (cutout_label["left"] - 40 <= line["left"] <= cutout_label["left"] + 350):
            continue
        match = price_pattern.search(line["text"])
        if match and "전주" not in _compact(line["text"]):
            return float(match.group(1))

    # OCR가 '$'와 숫자를 서로 다른 상자로 읽는 경우의 마지막 보완 경로다.
    for line in candidates:
        if not (cutout_label["left"] - 30 <= line["left"] <= cutout_label["left"] + 350):
            continue
        match = re.fullmatch(r"\s*([01]\.\d{2})\s*", line["text"])
        if match:
            return float(match.group(1))
    raise RuntimeError(f"{market_name} 컷아웃 가격을 읽지 못했습니다.")


def _find_beef_slaughter_count(lines: list[dict[str, Any]], page_width: float, page_height: float) -> int:
    slaughter_label = _find_beef_slaughter_label(lines)

    candidates = sorted(
        (
            line
            for line in lines
            if slaughter_label["top"] <= line["top"] <= slaughter_label["top"] + 850
            and "전주" not in _compact(line["text"])
        ),
        key=lambda line: line["top"],
    )
    for line in candidates:
        count = _korean_head_to_thousands(line["text"])
        if count is not None:
            return count
    raise RuntimeError("소고기 도축두수를 읽지 못했습니다.")


def _find_beef_previous_slaughter_count(lines: list[dict[str, Any]], page_width: float, page_height: float) -> int:
    """소고기 도축두수 카드의 '전 주' 수치를 천두 단위로 반환합니다."""
    slaughter_label = _find_beef_slaughter_label(lines)
    candidates = sorted(
        (
            line
            for line in lines
            if slaughter_label["top"] <= line["top"] <= slaughter_label["top"] + 850
            and "전주" in _compact(line["text"])
        ),
        key=lambda line: line["top"],
    )
    for line in candidates:
        count = _korean_head_to_thousands(line["text"])
        if count is not None:
            return count
        compact = _compact(line["text"])
        match = re.search(r"전주\D*(\d{2,3})(?:천두|000두)?", compact)
        if match is not None:
            return int(match.group(1))
    raise RuntimeError("소고기 전 주 도축두수를 읽지 못했습니다.")


def _find_pork_slaughter_count(lines: list[dict[str, Any]], page_width: float, page_height: float) -> int:
    return _find_slaughter_count(lines, occurrence=1, previous_week=False, market_name="돼지고기")


def _find_pork_previous_slaughter_count(lines: list[dict[str, Any]], page_width: float, page_height: float) -> int:
    return _find_slaughter_count(lines, occurrence=1, previous_week=True, market_name="돼지고기")


def _find_slaughter_count(lines: list[dict[str, Any]], occurrence: int, previous_week: bool, market_name: str) -> int:
    slaughter_label = (
        _find_pork_label(lines, "도축두수", f"{market_name} 도축두수")
        if market_name == "돼지고기"
        else _find_label(lines, "도축두수", occurrence, f"{market_name} 도축두수")
    )
    candidates = sorted(
        (
            line
            for line in lines
            if slaughter_label["top"] <= line["top"] <= slaughter_label["top"] + 450
            and ("전주" in _compact(line["text"])) == previous_week
        ),
        key=lambda line: line["top"],
    )
    for line in candidates:
        count = _korean_head_to_thousands(line["text"])
        if count is not None:
            return count
        count = _loose_korean_head_to_thousands(line["text"])
        if count is not None:
            return count
    week_label = "전 주 " if previous_week else ""
    raise RuntimeError(f"{market_name} {week_label}도축두수를 읽지 못했습니다.")


def _find_beef_slaughter_label(lines: list[dict[str, Any]]) -> dict[str, Any]:
    return _find_label(lines, "도축두수", occurrence=0, label_name="소고기 도축두수")


def _find_label(lines: list[dict[str, Any]], term: str, occurrence: int, label_name: str) -> dict[str, Any]:
    labels = [line for line in sorted(lines, key=lambda line: line["top"]) if term in _compact(line["text"])]
    if len(labels) <= occurrence:
        raise RuntimeError(f"{label_name} 항목을 찾지 못했습니다.")
    return labels[occurrence]


def _find_pork_label(lines: list[dict[str, Any]], term: str, label_name: str) -> dict[str, Any]:
    """'U.S. pork market trends' 제목 바로 아래의 지표 레이블을 찾습니다."""
    pork_heading = next(
        (line for line in sorted(lines, key=lambda line: line["top"]) if "porkmarket" in _compact(line["text"]).lower()),
        None,
    )
    if pork_heading is None:
        raise RuntimeError("돼지고기 시장동향 카드를 찾지 못했습니다.")
    label = next(
        (
            line
            for line in sorted(lines, key=lambda line: line["top"])
            if line["top"] >= pork_heading["top"] and term in _compact(line["text"])
        ),
        None,
    )
    if label is None:
        raise RuntimeError(f"{label_name} 항목을 찾지 못했습니다.")
    return label


def _korean_head_to_thousands(value: str) -> int | None:
    """'54만 2,000두' 같은 표기를 천두 단위 정수로 변환합니다."""
    compact = re.sub(r"\s+", "", value)
    match = re.search(r"(\d+)만(?:(\d{1,3}(?:,\d{3})?)|(?:(\d+)천))?두", compact)
    if match is None:
        # OCR가 '54만 2,000두'의 한글 단위를 놓쳐 '542,000'처럼 읽는 경우다.
        plain_number = re.search(r"(?<![\d,])(\d{2,3}(?:,\d{3})+)(?![\d,])", compact)
        if plain_number is None:
            return None
        return int(plain_number.group(1).replace(",", "")) // 1_000

    ten_thousands = int(match.group(1))
    tail = match.group(2)
    thousands = int(match.group(3)) if match.group(3) else 0
    remainder = int(tail.replace(",", "")) if tail else thousands * 1000
    return (ten_thousands * 10_000 + remainder) // 1_000


def _loose_korean_head_to_thousands(value: str) -> int | None:
    """OCR가 '두' 단위를 누락한 '237만7,000' 표기를 보완합니다."""
    compact = re.sub(r"\s+", "", value)
    match = re.search(r"(\d{2,3})만(\d{1,3}(?:,\d{3})?)", compact)
    if match is None:
        return None
    return (int(match.group(1)) * 10_000 + int(match.group(2).replace(",", ""))) // 1_000


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)
