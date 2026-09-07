"""USMEF Korea 뉴스라인 PDF에서 소고기 주간 지표를 수집합니다."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any
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
    market_data: list[dict[str, object]] = []
    failures: list[str] = []

    for report_date, pdf_url in entries:
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
        "미국($/lb)": _find_beef_cutout_price(ocr_lines, page_width, page_height),
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
            for segment_index, start_ratio in enumerate((0.0, 0.12, 0.24, 0.36)):
                crop = pymupdf.Rect(
                    page.rect.width * 0.55,
                    page.rect.height * start_ratio,
                    page.rect.width,
                    page.rect.height * min(start_ratio + segment_ratio, 0.48),
                )
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=crop, alpha=False)
                image_path = Path(temporary_directory) / f"newsline_{segment_index}.png"
                image_path.write_bytes(pixmap.tobytes("png"))
                result = _get_ocr()(str(image_path))
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
    section = lines
    right_column_start = 0
    cutout_label = next((line for line in sorted(section, key=lambda line: line["top"])
                         if line["left"] >= right_column_start and "컷아웃" in _compact(line["text"])), None)
    if cutout_label is None:
        raise RuntimeError("소고기 컷아웃 항목을 찾지 못했습니다.")

    price_pattern = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
    candidates = sorted(
        (
            line
            for line in section
            if line["left"] >= right_column_start
            and cutout_label["top"] - 80 <= line["top"] <= cutout_label["top"] + 750
        ),
        key=lambda line: line["top"],
    )
    for line in candidates:
        match = price_pattern.search(line["text"])
        if match:
            return float(match.group(1))
    raise RuntimeError("소고기 컷아웃 가격을 읽지 못했습니다.")


def _find_beef_slaughter_count(lines: list[dict[str, Any]], page_width: float, page_height: float) -> int:
    section = lines
    right_column_start = 0
    slaughter_label = next((line for line in sorted(section, key=lambda line: line["top"])
                            if line["left"] >= right_column_start and "도축두수" in _compact(line["text"])), None)
    if slaughter_label is None:
        raise RuntimeError("소고기 도축두수 항목을 찾지 못했습니다.")

    candidates = sorted(
        (
            line
            for line in section
            if line["left"] >= right_column_start
            and slaughter_label["top"] <= line["top"] <= slaughter_label["top"] + 850
            and "전주" not in _compact(line["text"])
        ),
        key=lambda line: line["top"],
    )
    for line in candidates:
        count = _korean_head_to_thousands(line["text"])
        if count is not None:
            return count
    raise RuntimeError("소고기 도축두수를 읽지 못했습니다.")


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


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)
