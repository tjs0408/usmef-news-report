"""USMEF Korea 뉴스라인 PDF에서 소고기 주간 지표를 수집합니다."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from functools import lru_cache
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from typing import Any, Callable, Literal
from urllib.parse import urlencode, urljoin
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

import pymupdf
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from openpyxl import load_workbook
from rapidocr import ModelType, OCRVersion, RapidOCR


NEWSLINE_URL = "https://www.usmef.co.kr/main/newsline.php"
EXCHANGE_RATE_API_URL = "https://stock.naver.com/api/stockSecurity/exchange-rates/v2/{currency_code}/daily"
AHDB_EU_PIG_PRICES_URL = (
    "https://projectblue.blob.core.windows.net/media/Default/Market%20Intelligence/"
    "pork/Prices/Deadweight%20pig%20prices/EU%20DW%20pg%20prices/"
    "EU%20deadweight%20pig%20prices.xlsx"
)
JZ_TAMAGO_EGG_PRICE_URL = "https://www.jz-tamago.co.jp/business/souba/{year:04d}/{month:02d}/{day:02d}/"
USDA_REPORT_ARCHIVE_URL = "https://mymarketnews.ams.usda.gov/filerepo/reports"
CEPEA_FRANGO_PRICE_SERIES_URL = "https://cepea.org.br/br/indicador/series/frango.aspx?id=181"
MLA_STATISTICS_API_URL = "https://api-mlastatistics.mla.com.au"
MLA_NLRS_SLAUGHTER_EMBED_INFO_URL = (
    "https://app.nlrsreports.mla.com.au/prices-markets/nlrs-slaughter/getembedinfo"
)
MLA_POWERBI_ORIGIN = "https://app.powerbi.com"
REQUEST_TIMEOUT_SECONDS = 60
USDA_REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "USMEF-Weekly-Market-Report/1.0 (+https://github.com/tjs0408/usmef-news-report)"


class MlaRecentStatisticsWindowError(RuntimeError):
    """MLA Statistics API가 최근 7일 데이터를 아직 허용하지 않는 경우입니다."""


def _cepea_price_series_reader_script() -> Path:
    return Path(__file__).resolve().parents[1] / "work" / "read_cepea_price_series.ps1"


def fetch_first_page_market_data() -> list[dict[str, object]]:
    """뉴스라인 1페이지 전체의 소고기 컷아웃·도축두수를 반환합니다.

    USMEF Korea의 뉴스라인은 이미지 기반 PDF로 제공됩니다. 따라서 최신 PDF의
    첫 페이지를 고해상도로 렌더링한 뒤, 한국어 OCR로 필요한 값만 읽습니다.
    """
    entries = _find_first_page_pdf_entries(_download_text(NEWSLINE_URL))
    return _fetch_market_data_from_entries(entries)


def fetch_market_data_for_report_dates(
    report_dates: set[date],
    progress_callback: Callable[[int, int, date, Literal["started", "completed"]], None] | None = None,
) -> list[dict[str, object]]:
    """지정한 발행일의 뉴스라인 PDF에서 소고기 지표를 수집합니다.

    엑셀의 금요일 주차 행은 다음 주 수요일에 발행된 뉴스라인과 연결됩니다.
    필요한 행만 채울 때에는 전체 첫 페이지를 OCR 처리하지 않도록 이 함수를 씁니다.
    """
    all_entries = _find_first_page_pdf_entries(_download_text(NEWSLINE_URL))
    entries = [
        entry
        for entry in all_entries
        if entry[0].date() in report_dates
    ]
    missing_dates = sorted(report_dates - {report_date.date() for report_date, _ in entries})
    latest_published_date = max((report_date.date() for report_date, _ in all_entries), default=None)
    unavailable_history = [
        report_date
        for report_date in missing_dates
        if latest_published_date is None or report_date <= latest_published_date
    ]
    if unavailable_history:
        missing_text = ", ".join(report_date.isoformat() for report_date in unavailable_history)
        raise RuntimeError(f"뉴스라인 1페이지에서 요청한 발행일을 찾지 못했습니다: {missing_text}")
    return _fetch_market_data_from_entries(entries, progress_callback)


def fetch_usd_krw_exchange_rates(exchange_dates: set[date]) -> dict[date, float]:
    """네이버 증권의 날짜별 USD/KRW 매매기준율을 반환합니다."""
    return _fetch_naver_exchange_rates(exchange_dates, "USD")


def fetch_eur_krw_exchange_rates(exchange_dates: set[date]) -> dict[date, float]:
    """네이버 증권의 EUR/KRW 매매기준율을 반환합니다.

    돼지-EU 양식의 기준일은 일요일이므로, 휴장일에는 직전 영업일 값을 사용합니다.
    """
    return _fetch_naver_exchange_rates(exchange_dates, "EUR", use_previous_business_day=True)


def fetch_jpy_krw_exchange_rates(exchange_dates: set[date]) -> dict[date, float]:
    """네이버 증권의 날짜별 JPY/KRW 매매기준율(100엔 기준)을 반환합니다."""
    return _fetch_naver_exchange_rates(exchange_dates, "JPY")


def fetch_brl_krw_exchange_rates(exchange_dates: set[date]) -> dict[date, float]:
    """네이버 증권의 날짜별 BRL/KRW 매매기준율을 반환합니다."""
    return _fetch_naver_exchange_rates(exchange_dates, "BRL")


def fetch_aud_krw_exchange_rates(exchange_dates: set[date]) -> dict[date, float]:
    """네이버 증권의 날짜별 AUD/KRW 매매기준율을 반환합니다."""
    return _fetch_naver_exchange_rates(exchange_dates, "AUD", use_previous_business_day=True)


def fetch_mla_australia_cattle_data(target_dates: set[date]) -> dict[date, dict[str, float]]:
    """MLA의 주간 소 도축 합계와 Eastern States Young Cattle Indicator를 반환합니다.

    양식의 기준일은 목요일이다. 주간 도축 합계는 다음 날 금요일에 끝나는
    NLRS 주간 보고서를, EYCI는 목요일 기준일의 지표를 사용한다.
    """
    if not target_dates:
        return {}

    slaughter_dates = {item + timedelta(days=1) for item in target_dates}
    slaughter_by_date: dict[date, float] = {item: 0.0 for item in slaughter_dates}
    failures: list[str] = []
    # 최신 주차는 주별 Statistics API 합계와 화면의 공식 National Count가
    # 일시적으로 다를 수 있다. 따라서 MLA 화면의 Latest Report에 표시되는
    # 기준일과 공식 합계를 먼저 읽고, 해당 금요일과 정확히 일치할 때만 쓴다.
    latest_report_date, latest_report_count = _fetch_mla_nlrs_latest_slaughter_report()
    # MLA의 National Slaughter 엔드포인트는 여러 주차를 한 번에 요청하면
    # HTTP 500을 반환하는 경우가 있어, 주차별로 나누어 안정적으로 조회한다.
    for slaughter_date in sorted(slaughter_dates):
        if slaughter_date == latest_report_date:
            slaughter_by_date[slaughter_date] = latest_report_count
            continue
        if slaughter_date > latest_report_date:
            # 다음 주 공식 보고서가 아직 공개되지 않았다. 다음 생성 때 재시도한다.
            continue
        parameters = {
            "fromDate": slaughter_date.isoformat(),
            "toDate": slaughter_date.isoformat(),
            "species": "Cattle",
        }
        recent_window = False
        for state_id in ("NSW", "QLD", "SA", "TAS", "VIC", "WA"):
            state_parameters = {**parameters, "stateID": state_id}
            try:
                payload = _download_mla_json("/report/10", state_parameters)
                for item in payload.get("data", []):
                    report_date = date.fromisoformat(str(item["result_date"]))
                    if report_date == slaughter_date:
                        slaughter_by_date[report_date] += float(item["slaughter_count"])
            except MlaRecentStatisticsWindowError:
                # 기존 통계 API는 최근 7일을 차단한다. 화면의 Latest Report를 쓴다.
                recent_window = True
                break
            except (KeyError, TypeError, ValueError, OSError) as error:
                failures.append(f"{slaughter_date.isoformat()} {state_id} 주간 도축량: {error}")
        if recent_window:
            failures.append(f"{slaughter_date.isoformat()} MLA Statistics API의 최근 주차 조회 제한")

    try:
        eyci_payload = _download_mla_json(
            "/report/5",
            {
                "fromDate": min(target_dates).isoformat(),
                "toDate": max(target_dates).isoformat(),
                "indicatorID": "0",
            },
        )
        eyci_by_date = {
            date.fromisoformat(str(item["calendar_date"])): float(item["indicator_value"])
            for item in eyci_payload.get("data", [])
        }
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise RuntimeError("MLA의 Eastern States Young Cattle Indicator를 읽지 못했습니다.") from error

    results: dict[date, dict[str, float]] = {}
    for target_date in sorted(target_dates):
        slaughter_date = target_date + timedelta(days=1)
        if slaughter_by_date.get(slaughter_date, 0.0) <= 0:
            failures.append(f"{slaughter_date.isoformat()}: MLA 주간 소 도축 합계를 찾지 못했습니다.")
            continue
        eyci_value = eyci_by_date.get(target_date)
        if eyci_value is None:
            failures.append(f"{target_date.isoformat()}: MLA EYCI 값을 찾지 못했습니다.")
            continue
        results[target_date] = {
            "slaughterCount": slaughter_by_date[slaughter_date],
            "eyci": eyci_value,
        }
    # 최신 주차는 MLA가 아직 공식 집계를 게시하지 않아 HTTP 500을 반환할 수 있다.
    # 이 경우 보고서 전체를 실패시키지 않고, 다음 실행 때 채울 수 있도록 빈 결과를 돌린다.
    return results


def fetch_cepea_brazil_chicken_prices(target_dates: set[date]) -> dict[date, float]:
    """CEPEA 동결 닭고기 가격 시리즈의 À vista R$/kg 값을 반환합니다.

    CEPEA 가격 시리즈는 과거 데이터가 포함된 Excel 97-2003 파일로 제공된다.
    해당 파일은 일부 일반 XLS 파서가 읽지 못하는 형식이므로, 이 프로그램이
    보고서 저장에 사용하는 Microsoft Excel로 읽어 원자료의 날짜·값을 보존한다.
    """
    if not target_dates:
        return {}
    prices = _read_cepea_brazil_chicken_prices(target_dates)
    return prices


def fetch_cepea_brazil_chicken_price_series(year: int) -> dict[date, float]:
    """CEPEA 가격 시리즈에서 해당 연도의 모든 거래일 À vista R$/kg 값을 반환합니다."""
    first_day = date(year, 1, 1)
    next_year = date(year + 1, 1, 1)
    requested_dates = {first_day + timedelta(days=offset) for offset in range((next_year - first_day).days)}
    return _read_cepea_brazil_chicken_prices(requested_dates)


def fetch_cepea_brazil_chicken_prices_for_period(start_date: date, end_date: date) -> dict[date, float]:
    """CEPEA 원본에서 기간 내에 실제로 존재하는 거래일 가격을 날짜순으로 반환합니다."""
    if end_date < start_date:
        return {}
    requested_dates = {
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    }
    return _read_cepea_brazil_chicken_prices(requested_dates)


def _read_cepea_brazil_chicken_prices(target_dates: set[date]) -> dict[date, float]:
    """CEPEA 원본 XLS에서 요청 날짜에 존재하는 가격만 읽는 내부 함수입니다."""
    if os.name != "nt":
        raise RuntimeError("CEPEA 브라질 닭고기 가격 시리즈는 Windows의 Microsoft Excel에서 읽어야 합니다.")
    try:
        series_bytes = _download_cepea_bytes(CEPEA_FRANGO_PRICE_SERIES_URL)
    except OSError as error:
        raise RuntimeError("CEPEA의 브라질 닭고기 가격 시리즈를 내려받지 못했습니다.") from error

    with TemporaryDirectory() as temporary_directory:
        source_path = Path(temporary_directory) / "cepea_frango_price_series.xls"
        dates_path = Path(temporary_directory) / "target_dates.json"
        source_path.write_bytes(series_bytes)
        dates_path.write_text(json.dumps(sorted(item.isoformat() for item in target_dates)), encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(_cepea_price_series_reader_script()), "-SourcePath", str(source_path),
                    "-TargetDatesPath", str(dates_path),
                ],
                check=True, capture_output=True, text=True, encoding="utf-8", timeout=90,
            )
            parsed = json.loads(completed.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            raise RuntimeError("CEPEA의 브라질 닭고기 가격 시리즈를 읽지 못했습니다.") from error
    return {date.fromisoformat(item_date): float(price) for item_date, price in parsed.items()}


def fetch_jz_tokyo_egg_prices(target_dates: set[date]) -> dict[date, float]:
    """JA 전농타마고의 지정일 도쿄 M란 기준치(엔/kg)를 반환합니다."""
    prices: dict[date, float] = {}
    failures: list[str] = []
    for target_date in sorted(target_dates):
        url = JZ_TAMAGO_EGG_PRICE_URL.format(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
        )
        try:
            soup = BeautifulSoup(_download_jz_tamago_bytes(url), "html.parser")
            tokyo_table = soup.select_one("#tokyo table")
            if tokyo_table is None:
                raise ValueError("도쿄 가격표를 찾지 못했습니다.")
            m_row = next(
                (
                    row
                    for row in tokyo_table.select("tbody tr")
                    if row.find("th") is not None and row.find("th").get_text(strip=True) == "M"
                ),
                None,
            )
            if m_row is None:
                raise ValueError("도쿄 M란 행을 찾지 못했습니다.")
            cells = m_row.find_all("td")
            if len(cells) < 2:
                raise ValueError("도쿄 M란 기준치 칸을 찾지 못했습니다.")
            prices[target_date] = float(cells[1].get_text(strip=True).replace(",", ""))
        except (OSError, ValueError) as error:
            # 당일·최근 주차 가격은 현지 공개 시점 차이로 비어 있을 수 있다.
            # 이 경우 다음 생성에서 같은 행을 재시도하도록 빈칸으로 남긴다.
            if target_date >= date.today() - timedelta(days=7):
                continue
            failures.append(f"{target_date.isoformat()}: {error}")
    if failures:
        raise RuntimeError("JA 전농타마고의 도쿄 M란 기준치를 읽지 못했습니다.\n" + "\n".join(failures))
    return prices


def fetch_usda_us_egg_data(target_dates: set[date]) -> dict[date, dict[str, float]]:
    """USDA 주간 재고·계란 가격 보고서에서 미국 계란 지표를 반환합니다.

    양식의 기준일은 금요일이다. 재고량은 같은 주 월요일(금요일 - 4일)에
    발표된 Slug 1427 보고서를, Large 가격은 해당 금요일에 발행된 Slug 2848
    보고서를 사용한다.
    """
    if not target_dates:
        return {}

    inventory_reports = _find_usda_report_documents("1427")
    price_reports = _find_usda_report_documents("2848")
    latest_inventory_report_date = max(
        (report["reportDate"] for report in inventory_reports),
        default=None,
    )
    latest_price_report_date = max(
        (report["publishedDate"] for report in price_reports),
        default=None,
    )
    results: dict[date, dict[str, float]] = {}
    failures: list[str] = []

    for week_ended in sorted(target_dates):
        inventory_date = week_ended - timedelta(days=4)
        inventory_report = _select_usda_report(inventory_reports, "reportDate", inventory_date)
        price_report = _select_usda_report(price_reports, "publishedDate", week_ended)
        if inventory_report is None:
            if latest_inventory_report_date is not None and inventory_date > latest_inventory_report_date:
                continue
            failures.append(f"{week_ended.isoformat()}: Slug ID 1427의 {inventory_date.isoformat()} 재고 보고서를 찾지 못했습니다.")
            continue
        if price_report is None:
            # 아직 USDA 아카이브에 게시되지 않은 최신 주차는 다른 시트 생성까지
            # 막지 않는다. 다음 실행 때 같은 빈 행을 다시 확인해 채운다.
            if latest_price_report_date is not None and week_ended > latest_price_report_date:
                continue
            failures.append(f"{week_ended.isoformat()}: Slug ID 2848의 {week_ended.isoformat()} 가격 보고서를 찾지 못했습니다.")
            continue

        try:
            inventory_total = _extract_usda_inventory_total(_download_usda_bytes(str(inventory_report["url"])))
            large_average_price = _extract_usda_large_average_price(_download_usda_bytes(str(price_report["url"])))
            results[week_ended] = {
                "weeklyInventory": inventory_total,
                "largeAveragePrice": large_average_price,
            }
        except RuntimeError as error:
            failures.append(f"{week_ended.isoformat()}: {error}")

    if failures:
        raise RuntimeError("USDA 미국 계란 보고서를 읽지 못했습니다.\n" + "\n".join(failures))
    return results


def fetch_usda_us_chicken_data(target_dates: set[date]) -> dict[date, dict[str, float]]:
    """USDA의 미국 닭고기 주간도축량·WOG 가격을 반환합니다.

    Slug 3208과 3646 모두 양식의 기준일과 같은 Published Date의 보고서를
    사용한다. 3208에서는 ``Chicken (Young)``의 WTD를, 3646에서는 National
    Composite WOGS의 Wtd Avg를 각각 읽는다.
    """
    if not target_dates:
        return {}

    slaughter_reports = _find_usda_report_documents("3208")
    price_reports = _find_usda_report_documents("3646")
    latest_slaughter_date = max((report["publishedDate"] for report in slaughter_reports), default=None)
    latest_price_date = max((report["publishedDate"] for report in price_reports), default=None)
    results: dict[date, dict[str, float]] = {}
    failures: list[str] = []
    for week_ended in sorted(target_dates):
        slaughter_report = _select_usda_report(slaughter_reports, "publishedDate", week_ended)
        price_report = _select_usda_report(price_reports, "publishedDate", week_ended)
        if slaughter_report is None:
            if latest_slaughter_date is not None and week_ended > latest_slaughter_date:
                continue
            failures.append(f"{week_ended.isoformat()}: Slug ID 3208의 해당 발행일 보고서를 찾지 못했습니다.")
            continue
        if price_report is None:
            if latest_price_date is not None and week_ended > latest_price_date:
                continue
            failures.append(f"{week_ended.isoformat()}: Slug ID 3646의 해당 발행일 보고서를 찾지 못했습니다.")
            continue
        try:
            results[week_ended] = {
                "weeklySlaughter": _extract_usda_young_chicken_wtd(
                    _download_usda_bytes(str(slaughter_report["url"]))
                ),
                "wtdAvg": _extract_usda_wog_weighted_average(
                    _download_usda_bytes(str(price_report["url"]))
                ),
            }
        except RuntimeError as error:
            failures.append(f"{week_ended.isoformat()}: {error}")

    if failures:
        raise RuntimeError("USDA 미국 닭고기 보고서를 읽지 못했습니다.\n" + "\n".join(failures))
    return results


def _fetch_naver_exchange_rates(
    exchange_dates: set[date],
    currency_code: str,
    use_previous_business_day: bool = False,
) -> dict[date, float]:
    """네이버 증권 하나은행 매매기준율을 지정 통화·날짜로 반환합니다."""
    if not exchange_dates:
        return {}

    rates: dict[date, float] = {}
    available_rates: dict[date, float] = {}
    cursor: str | None = None
    oldest_requested_date = min(exchange_dates)
    while True:
        parameters: dict[str, str] = {"bankType": "hana", "size": "20"}
        if cursor:
            parameters["cursor"] = cursor
        url = EXCHANGE_RATE_API_URL.format(currency_code=currency_code)
        response = _download_exchange_rate_bytes(f"{url}?{urlencode(parameters)}", currency_code)
        try:
            payload = json.loads(response.decode("utf-8"))
            items = payload["items"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError(f"네이버 증권에서 {currency_code}/KRW 환율 데이터를 읽지 못했습니다.") from error

        page_dates: list[date] = []
        for item in items:
            item_date = date.fromisoformat(str(item["date"]))
            page_dates.append(item_date)
            available_rates[item_date] = float(str(item["saleBaseRate"]).replace(",", ""))
            if item_date in exchange_dates:
                rates[item_date] = available_rates[item_date]

        if exchange_dates.issubset(rates) or not payload.get("hasNext"):
            break
        if page_dates and min(page_dates) < oldest_requested_date:
            break
        cursor = payload.get("cursor")
        if not cursor:
            break

    if use_previous_business_day:
        for target_date in exchange_dates - set(rates):
            prior_dates = [item_date for item_date in available_rates if item_date <= target_date]
            if prior_dates:
                rates[target_date] = available_rates[max(prior_dates)]

    # 최신 영업일의 환율이 아직 게시되지 않은 경우는 빈 결과로 남긴다.
    # 호출 측에서 해당 행만 보류하고 다음 생성 때 다시 조회한다.
    return rates


def fetch_ahdb_germany_pig_prices(target_dates: set[date]) -> dict[date, float]:
    """AHDB의 주간 Grade E 독일 돼지고기 가격(€/100kg)을 날짜별로 반환합니다."""
    if not target_dates:
        return {}
    try:
        workbook = load_workbook(
            BytesIO(_download_ahdb_bytes(AHDB_EU_PIG_PRICES_URL)),
            read_only=True,
            data_only=True,
        )
        worksheet = workbook["E grade euro"]
    except (KeyError, OSError, ValueError) as error:
        raise RuntimeError("AHDB의 EU 돼지고기 가격 파일을 읽지 못했습니다.") from error

    try:
        header_row, week_ended_column, germany_column = _find_ahdb_germany_columns(worksheet)
        prices: dict[date, float] = {}
        for values in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
            week_ended = values[week_ended_column]
            germany_price = values[germany_column]
            if isinstance(week_ended, datetime):
                week_ended = week_ended.date()
            if week_ended in target_dates and isinstance(germany_price, (int, float)):
                prices[week_ended] = float(germany_price)
    finally:
        workbook.close()
    return prices


def _fetch_market_data_from_entries(
    entries: list[tuple[datetime, str]],
    progress_callback: Callable[[int, int, date, Literal["started", "completed"]], None] | None = None,
) -> list[dict[str, object]]:
    market_data: list[dict[str, object]] = []
    failures: list[str] = []

    for index, (report_date, pdf_url) in enumerate(entries, start=1):
        if progress_callback is not None:
            progress_callback(index, len(entries), report_date.date(), "started")
        try:
            market_data.append(_extract_market_data(pdf_url, report_date))
            if progress_callback is not None:
                progress_callback(index, len(entries), report_date.date(), "completed")
        except RuntimeError as error:
            failures.append(f"{report_date:%Y-%m-%d}: {error}")

    if failures:
        details = "\n".join(failures)
        raise RuntimeError(f"뉴스라인 {len(failures)}건을 읽지 못했습니다.\n{details}")
    return market_data


def fetch_latest_market_data() -> dict[str, object]:
    """하위 호환용으로 최신 뉴스라인 한 건을 반환합니다."""
    return fetch_first_page_market_data()[0]


@lru_cache(maxsize=32)
def _extract_market_data(pdf_url: str, report_date: datetime) -> dict[str, object]:
    """한 서버 실행 중 이미 성공한 뉴스라인은 다시 내려받거나 OCR하지 않습니다."""
    pdf_bytes = _download_bytes(pdf_url)
    try:
        # USMEF 뉴스라인 PDF는 화면상 이미지처럼 보이지만 대부분 선택 가능한
        # 한글 텍스트 레이어를 갖고 있다. 이를 먼저 읽으면 OCR 다섯 회를 생략할 수 있다.
        return _validate_market_data(_extract_market_data_from_pdf_text(pdf_bytes, report_date))
    except RuntimeError:
        # 과거 호 또는 레이아웃이 달라 텍스트 카드에서 값을 찾지 못한 경우만 OCR을 쓴다.
        # OCR 경로는 기존 규칙을 그대로 보존해 추출 정확도를 우선한다.
        try:
            # 육류 카드가 위치하는 상·중단만 먼저 읽어 OCR 횟수와 이미지 면적을 줄인다.
            ocr_lines, page_width, page_height = _read_pdf_with_ocr(pdf_bytes, targeted=True)
            return _validate_market_data(
                _extract_market_data_from_ocr_lines(ocr_lines, page_width, page_height, report_date)
            )
        except RuntimeError:
            # 오래된 호처럼 카드 위치가 크게 다른 경우에는 기존 전체 범위 OCR로 재시도한다.
            ocr_lines, page_width, page_height = _read_pdf_with_ocr(pdf_bytes, targeted=False)
            return _validate_market_data(
                _extract_market_data_from_ocr_lines(ocr_lines, page_width, page_height, report_date)
            )


def _extract_market_data_from_ocr_lines(
    ocr_lines: list[dict[str, Any]],
    page_width: float,
    page_height: float,
    report_date: datetime,
) -> dict[str, object]:
    """OCR 줄 목록에서 소·돼지 시장 지표를 추출합니다."""
    return {
        "구분": report_date.date(),
        "도축두수": _find_beef_slaughter_count(ocr_lines, page_width, page_height),
        "usda 수정": _find_beef_previous_slaughter_count(ocr_lines, page_width, page_height),
        "미국($/lb)": _find_beef_cutout_price(ocr_lines, page_width, page_height),
        "돼지 도축두수": _find_pork_slaughter_count(ocr_lines, page_width, page_height),
        "돼지 usda 수정": _find_pork_previous_slaughter_count(ocr_lines, page_width, page_height),
        "돼지 미국($/lb)": _find_pork_cutout_price(ocr_lines, page_width, page_height),
    }


def _validate_market_data(market_data: dict[str, object]) -> dict[str, object]:
    """명백한 OCR·텍스트 레이어 오인식은 전체 OCR 재시도를 유도합니다."""
    ranges = {
        "도축두수": (200, 1_000),
        "usda 수정": (200, 1_000),
        "미국($/lb)": (1.0, 8.0),
        "돼지 도축두수": (1_000, 3_500),
        "돼지 usda 수정": (1_000, 3_500),
        "돼지 미국($/lb)": (0.2, 3.0),
    }
    for field, (minimum, maximum) in ranges.items():
        value = market_data.get(field)
        if not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
            raise RuntimeError(f"뉴스라인의 {field} 값이 유효 범위를 벗어났습니다.")
    return market_data


def _extract_market_data_from_pdf_text(pdf_bytes: bytes, report_date: datetime) -> dict[str, object]:
    """USMEF PDF의 선택 가능한 카드 텍스트에서 시장 지표를 읽습니다.

    동일한 PDF를 5개 조각으로 렌더링해 OCR하는 기존 방식보다 훨씬 빠르며, PDF에
    텍스트 레이어가 없는 호는 호출 측에서 기존 OCR 경로로 자동 전환한다.
    """
    document = None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page = document[0]
        card_left = float(page.rect.width) * 0.55
        blocks = [
            {
                "left": float(x0),
                "top": float(y0),
                "text": str(text),
            }
            for x0, y0, _x1, _y1, text, *_rest in page.get_text("blocks", sort=True)
            if float(x0) >= card_left and str(text).strip()
        ]
    except Exception as error:
        raise RuntimeError("뉴스라인 PDF의 텍스트 레이어를 읽을 수 없습니다.") from error
    finally:
        if document is not None:
            document.close()

    slaughter_headers = [block for block in blocks if "도축두수" in _compact(block["text"])]
    cutout_headers = [block for block in blocks if "컷아웃" in _compact(block["text"])]
    if len(slaughter_headers) < 2 or len(cutout_headers) < 2:
        raise RuntimeError("뉴스라인 PDF의 시장 카드 텍스트를 찾지 못했습니다.")

    beef_slaughter_header, pork_slaughter_header = slaughter_headers[:2]
    beef_cutout_header, pork_cutout_header = cutout_headers[:2]
    beef_slaughter = _native_card_head_count(blocks, beef_slaughter_header, previous_week=False)
    beef_previous_slaughter = _native_card_head_count(blocks, beef_slaughter_header, previous_week=True)
    pork_slaughter = _native_card_head_count(blocks, pork_slaughter_header, previous_week=False)
    pork_previous_slaughter = _native_card_head_count(blocks, pork_slaughter_header, previous_week=True)
    beef_cutout = _native_card_cutout_price(blocks, beef_cutout_header)
    pork_cutout = _native_card_cutout_price(blocks, pork_cutout_header)

    return {
        "구분": report_date.date(),
        "도축두수": beef_slaughter,
        "usda 수정": beef_previous_slaughter,
        "미국($/lb)": beef_cutout,
        "돼지 도축두수": pork_slaughter,
        "돼지 usda 수정": pork_previous_slaughter,
        "돼지 미국($/lb)": pork_cutout,
    }


def _native_card_head_count(
    blocks: list[dict[str, Any]],
    header: dict[str, Any],
    *,
    previous_week: bool,
) -> int:
    """선택 가능한 USMEF 도축두수 카드에서 현재 또는 전 주 값을 읽습니다."""
    header_top = float(header["top"])
    header_left = float(header["left"])
    for block in blocks:
        top = float(block["top"])
        if not (header_top < top <= header_top + 250) or abs(float(block["left"]) - header_left) > 80:
            continue
        text = str(block["text"])
        is_previous = "전주" in _compact(text)
        if is_previous != previous_week:
            continue
        count = _korean_head_to_thousands(text) or _loose_korean_head_to_thousands(text)
        if count is not None:
            return count
    week_label = "전 주 " if previous_week else ""
    raise RuntimeError(f"텍스트 카드에서 {week_label}도축두수를 찾지 못했습니다.")


def _native_card_cutout_price(blocks: list[dict[str, Any]], header: dict[str, Any]) -> float:
    """선택 가능한 USMEF 컷아웃 카드에서 현재 달러/파운드 가격을 읽습니다."""
    header_top = float(header["top"])
    header_left = float(header["left"])
    for block in blocks:
        top = float(block["top"])
        if not (header_top < top <= header_top + 160) or abs(float(block["left"]) - header_left) > 80:
            continue
        compact = _compact(str(block["text"]))
        if "전주" in compact:
            continue
        match = re.search(r"\$\s*(\d+(?:\.\d+)?)", str(block["text"]))
        if match is not None:
            return float(match.group(1))
    raise RuntimeError("텍스트 카드에서 컷아웃 가격을 찾지 못했습니다.")


def _download_text(url: str) -> str:
    return _download_bytes(url).decode("utf-8", errors="replace")


def _download_mla_json(path: str, parameters: dict[str, str]) -> dict[str, object]:
    """MLA Statistics API의 공개 JSON 응답을 읽습니다."""
    url = f"{MLA_STATISTICS_API_URL}{path}?{urlencode(parameters)}"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if "Please provide date range 7 days before today!" in detail:
            raise MlaRecentStatisticsWindowError("MLA 통계 API의 최근 7일 조회 제한") from error
        raise OSError(f"HTTP {error.code}: {detail or error.reason}") from error


def _mla_powerbi_headers(access_token: str) -> dict[str, str]:
    """MLA 공개 NLRS 대시보드의 단기 EmbedToken 요청 헤더를 만듭니다."""
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"EmbedToken {access_token}",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-HostEnv": "Embed for Customers",
        "Origin": MLA_POWERBI_ORIGIN,
        "User-Agent": USER_AGENT,
    }


def _download_json_request(url: str, headers: dict[str, str], body: bytes | None = None) -> dict[str, Any]:
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("MLA 최신 NLRS 보고서를 조회하지 못했습니다.") from error


def _decode_powerbi_cluster_url(access_token: str) -> str:
    try:
        encoded = access_token.split(".", 1)[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        return str(json.loads(base64.b64decode(padded)) ["clusterUrl"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("MLA 최신 보고서 연결 정보를 읽지 못했습니다.") from error


@lru_cache(maxsize=1)
def _fetch_mla_nlrs_latest_slaughter_report() -> tuple[date, float]:
    """MLA NLRS 화면 Latest Report의 기준일과 공식 소 도축 합계를 읽습니다."""
    embed_info = _download_json_request(
        MLA_NLRS_SLAUGHTER_EMBED_INFO_URL,
        {"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    access_token = str(embed_info.get("accessToken", ""))
    configs = embed_info.get("reportConfig")
    if not access_token or not isinstance(configs, list) or not configs:
        raise RuntimeError("MLA 최신 보고서 접근 정보를 받지 못했습니다.")
    report_id = str(configs[0].get("reportId", ""))
    if not report_id:
        raise RuntimeError("MLA 최신 보고서 식별자를 받지 못했습니다.")

    cluster_url = _decode_powerbi_cluster_url(access_token).rstrip("/")
    headers = _mla_powerbi_headers(access_token)
    model_payload = _download_json_request(
        f"{cluster_url}/explore/reports/{report_id}/modelsAndExploration?preferReadOnlySession=true",
        headers,
    )
    models = model_payload.get("models")
    exploration = model_payload.get("exploration")
    if not isinstance(models, list) or not models or not isinstance(exploration, dict):
        raise RuntimeError("MLA 최신 보고서의 데이터 모델을 읽지 못했습니다.")

    source_query: dict[str, Any] | None = None
    selected_week_query: dict[str, Any] | None = None
    for section in exploration.get("sections", []):
        for visual in section.get("visualContainers", []):
            query_text = visual.get("query", "")
            if all(marker in query_text for marker in ("Slaughter.Contributor State", "Slaughter Count", "Latest Week Ending")):
                candidate = json.loads(query_text)
                candidate_select = candidate["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"].get("Select", [])
                if len(candidate_select) > 5:
                    source_query = candidate
            if "Metrics.Week Ending Selected" in query_text:
                selected_week_query = json.loads(query_text)
    if source_query is None or selected_week_query is None:
        raise RuntimeError("MLA 최신 보고서의 소 도축 표를 찾지 못했습니다.")

    # 표는 이미 Cattle + Latest Report로 필터되어 있다. 합계 열만 남겨 빠르게 조회한다.
    command = source_query["Commands"][0]["SemanticQueryDataShapeCommand"]
    query = command["Query"]
    query["Select"] = [query["Select"][5]]
    command["Binding"]["Primary"]["Groupings"][0]["Projections"] = [0]
    def query_body_for(visual_query: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": "1.0.0",
            "queries": [{
                "Query": visual_query,
                "ApplicationContext": {
                    "DatasetId": models[0].get("dbName"),
                    "Sources": [{"ReportId": report_id}],
                },
            }],
            "cancelQueries": [],
            "modelId": models[0].get("id"),
        }
    selected_week_response = _download_json_request(
        f"{cluster_url}/explore/querydata?synchronous=true",
        _mla_powerbi_headers(access_token),
        json.dumps(query_body_for(selected_week_query)).encode("utf-8"),
    )
    response = _download_json_request(
        f"{cluster_url}/explore/querydata?synchronous=true",
        _mla_powerbi_headers(access_token),
        json.dumps(query_body_for(source_query)).encode("utf-8"),
    )
    try:
        selected_week_data = selected_week_response["results"][0]["result"]["data"]["dsr"]["DS"][0]
        selected_week_text = selected_week_data["PH"][0]["DM0"][0]["M0"]
        selected_week_match = re.search(r"(\d{2}/\d{2}/\d{4})", str(selected_week_text))
        if selected_week_match is None:
            raise ValueError("기준일 형식을 찾지 못했습니다.")
        report_date = datetime.strptime(selected_week_match.group(1), "%d/%m/%Y").date()
        data = response["results"][0]["result"]["data"]["dsr"]["DS"][0]
        result_row = data["PH"][0]["DM0"][0]
        value = result_row["M0"] if "M0" in result_row else result_row["C"][0]
        return report_date, float(value)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("MLA 최신 보고서의 소 도축 합계 또는 기준일을 읽지 못했습니다.") from error


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise RuntimeError("USMEF 서버에서 뉴스라인 파일을 가져오지 못했습니다.") from error


def _download_exchange_rate_bytes(url: str, currency_code: str) -> bytes:
    """네이버 증권 환율 API를 브라우저 요청 형식으로 읽습니다."""
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://stock.naver.com/marketindex/exchange/FX_{currency_code}KRW/price",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise RuntimeError(f"네이버 증권에서 {currency_code}/KRW 환율 데이터를 가져오지 못했습니다.") from error


def _download_ahdb_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise RuntimeError("AHDB에서 EU 돼지고기 가격 파일을 가져오지 못했습니다.") from error


def _download_jz_tamago_bytes(url: str) -> bytes:
    """JA 전농타마고의 일별 계란 가격 페이지를 읽습니다."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise RuntimeError("JA 전농타마고에서 계란 가격을 가져오지 못했습니다.") from error


def _download_cepea_bytes(url: str) -> bytes:
    """CEPEA의 Excel 가격 시리즈를 Chrome 호환 요청으로 내려받습니다."""
    try:
        response = curl_requests.get(
            url,
            headers={"Accept": "application/vnd.ms-excel,*/*", "Referer": "https://cepea.org.br/br/indicador/frango.aspx"},
            impersonate="chrome",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content
    except Exception as error:
        raise RuntimeError("CEPEA에서 브라질 닭고기 가격 파일을 가져오지 못했습니다.") from error


def _find_usda_report_documents(slug_id: str) -> list[dict[str, object]]:
    """USDA 아카이브에서 Slug ID별 PDF 주소와 기준일을 읽습니다."""
    parameters = {
        "field_slug_id_value": slug_id,
        "name": "",
        "field_slug_title_value": "",
        "field_published_date_value": "",
        "field_report_date_end_value": "",
        "field_api_market_types_target_id": "All",
        "order": "",
        "sort": "",
    }
    url = f"{USDA_REPORT_ARCHIVE_URL}?{urlencode(parameters)}"
    try:
        soup = BeautifulSoup(_download_usda_bytes(url, accept="text/html,application/xhtml+xml"), "html.parser")
    except OSError as error:
        raise RuntimeError(f"Slug ID {slug_id} 보고서 목록을 가져오지 못했습니다.") from error

    reports: list[dict[str, object]] = []
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 7 or cells[0].get_text(strip=True) != slug_id:
            continue
        try:
            published_date = _parse_usda_archive_date(cells[3].get_text(" ", strip=True))
            report_date = date.fromisoformat(cells[4].get_text(strip=True))
        except ValueError:
            continue
        link = cells[-1].find("a", href=True)
        if link is None:
            continue
        reports.append(
            {
                "publishedDate": published_date,
                "reportDate": report_date,
                "url": urljoin(USDA_REPORT_ARCHIVE_URL, link["href"]),
            }
        )
    if not reports:
        raise RuntimeError(f"Slug ID {slug_id} 보고서 목록에서 PDF 주소를 찾지 못했습니다.")
    return reports


def _parse_usda_archive_date(value: str) -> date:
    """아카이브의 '08-21-2026 08:03:01 am' 형식을 날짜로 바꿉니다."""
    match = re.search(r"(\d{2})-(\d{2})-(\d{4})", value)
    if match is None:
        raise ValueError("USDA 발행일 형식을 읽지 못했습니다.")
    return datetime.strptime(match.group(0), "%m-%d-%Y").date()


def _select_usda_report(
    reports: list[dict[str, object]],
    date_field: str,
    target_date: date,
) -> dict[str, object] | None:
    """정정본이 있으면 가장 최근에 발행된 PDF를 우선합니다."""
    matches = [report for report in reports if report[date_field] == target_date]
    if not matches:
        return None
    return max(matches, key=lambda report: report["publishedDate"])


def _download_usda_bytes(url: str, accept: str = "application/pdf,*/*") -> bytes:
    """USDA Market News를 Chrome 호환 TLS 요청으로 읽습니다.

    USDA 아카이브는 일반 Python TLS 지문을 간헐적으로 차단하므로, Chrome 호환
    요청을 사용한다. 이 방식은 일반 브라우저에서 보고서를 여는 것과 같은 경로다.
    """
    try:
        response = curl_requests.get(
            url,
            headers={"Accept": accept, "Referer": USDA_REPORT_ARCHIVE_URL},
            impersonate="chrome",
            timeout=USDA_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content
    except Exception as error:
        raise RuntimeError("USDA Market News에서 보고서를 가져오지 못했습니다.") from error


def _extract_usda_inventory_total(pdf_bytes: bytes) -> float:
    """Slug 1427 첫 표의 Total 행·6-Area Total 값을 반환합니다."""
    try:
        rows = _extract_first_pdf_table(pdf_bytes, "주간 재고량")
        for row in rows:
            normalized = [_normalize_pdf_cell(value) for value in row]
            if len(normalized) >= 3 and normalized[0] == "total" and normalized[1] == "total":
                return _parse_usda_number(next(value for value in reversed(normalized) if value))
    except RuntimeError:
        pass

    text = _extract_pdf_text(pdf_bytes, "주간 재고량")
    total_row = re.search(r"(?ms)^\s*Total\s+([^\n]+)\n\s*Total\s*\n\s*% Change", text)
    if total_row is not None:
        values = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", total_row.group(1))
        if values:
            return _parse_usda_number(values[-1])
    raise RuntimeError("Slug ID 1427 첫 표에서 6-Area Total 값을 읽지 못했습니다.")


def _extract_usda_large_average_price(pdf_bytes: bytes) -> float:
    """Slug 2848 첫 표의 National Shell Eggs - Caged Large 평균가격을 반환합니다."""
    try:
        rows = _extract_first_pdf_table(pdf_bytes, "계란 가격")
        if rows:
            header = [_normalize_pdf_cell(value) for value in rows[0]]
            average_column = next(index for index, value in enumerate(header) if "average" in value and "price" in value)
            for row in rows[1:]:
                normalized = [_normalize_pdf_cell(value) for value in row]
                if normalized and normalized[0] == "large" and len(normalized) > average_column:
                    return _parse_usda_number(normalized[average_column])
    except (RuntimeError, StopIteration):
        pass

    text = _extract_pdf_text(pdf_bytes, "계란 가격")
    national_section = text.split("National Shell Eggs - Caged", 1)
    if len(national_section) == 2:
        first_table = national_section[1].split("Midwest Shell Eggs - Caged", 1)[0]
        large_row = re.search(
            r"(?m)^\s*Large\s+\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s+(\d+(?:\.\d+)?)",
            first_table,
        )
        if large_row is not None:
            return _parse_usda_number(large_row.group(1))
    raise RuntimeError("Slug ID 2848 첫 표에서 Large Average Price 값을 읽지 못했습니다.")


def _extract_usda_wog_weighted_average(pdf_bytes: bytes) -> float:
    """Slug 3646 첫 페이지의 National Composite WOGS Wtd Avg를 반환합니다."""
    text = _extract_pdf_text(pdf_bytes, "미국 닭고기 가격")
    section_match = re.search(
        r"(?is)WOG Trading by Size:\s*(.*?)(?:Whole Body Trading by Size:|Report For:)",
        text,
    )
    if section_match is not None:
        wogs_match = re.search(
            r"(?is)National Composite WOGS:\s*"
            r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*"
            r"(\d+(?:\.\d+)?)",
            section_match.group(1),
        )
        if wogs_match is not None:
            return _parse_usda_number(wogs_match.group(1))
    raise RuntimeError("Slug ID 3646 첫 페이지 WOG Trading by Size의 Wtd Avg를 읽지 못했습니다.")


def _extract_usda_young_chicken_wtd(pdf_bytes: bytes) -> float:
    """Slug 3208 첫 표의 Current Day Slaughter Chicken (Young) WTD를 반환합니다."""
    document = None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        # 3208은 열 좌표 순서가 중요하므로 정렬하지 않은 원본 텍스트를 쓴다.
        text = document[0].get_text("text")
    except Exception as error:
        raise RuntimeError("미국 닭고기 도축량 PDF를 읽지 못했습니다.") from error
    finally:
        if document is not None:
            document.close()
    current_day_section = text.split("Current Day Slaughter", 1)
    if len(current_day_section) == 2:
        chicken_row = re.search(
            r"(?is)Chicken\s*\(Young\)\s*((?:\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*){4})",
            current_day_section[1],
        )
        if chicken_row is not None:
            values = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", chicken_row.group(1))
            if len(values) >= 4:
                return _parse_usda_number(values[3])
    raise RuntimeError("Slug ID 3208 첫 표 Current Day Slaughter의 Chicken (Young) WTD를 읽지 못했습니다.")


def _extract_first_pdf_table(pdf_bytes: bytes, report_name: str) -> list[list[str | None]]:
    """텍스트 기반 USDA PDF의 첫 표를 구조적으로 추출합니다."""
    document = None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        tables = document[0].find_tables()
        if not tables.tables:
            raise RuntimeError(f"{report_name} PDF에서 표를 찾지 못했습니다.")
        return tables.tables[0].extract()
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"{report_name} PDF를 읽지 못했습니다.") from error
    finally:
        if document is not None:
            document.close()


def _extract_pdf_text(pdf_bytes: bytes, report_name: str) -> str:
    """표 선을 인식하지 못하는 USDA PDF에 대비한 정렬 텍스트 추출입니다."""
    document = None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        return document[0].get_text("text", sort=True)
    except Exception as error:
        raise RuntimeError(f"{report_name} PDF를 읽지 못했습니다.") from error
    finally:
        if document is not None:
            document.close()


def _normalize_pdf_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _parse_usda_number(value: str) -> float:
    match = re.search(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", value.replace(" ", ""))
    if match is None:
        raise RuntimeError("USDA 보고서의 숫자 값을 읽지 못했습니다.")
    return float(match.group(0).replace(",", ""))


def _find_ahdb_germany_columns(worksheet: Any) -> tuple[int, int, int]:
    """AHDB 원본의 주차·독일 열 위치를 헤더명으로 찾습니다."""
    for row_number, values in enumerate(worksheet.iter_rows(min_row=1, max_row=30, values_only=True), start=1):
        normalized = [str(value).strip() if value is not None else "" for value in values]
        if "Week ended" in normalized and "Germany" in normalized:
            return row_number, normalized.index("Week ended"), normalized.index("Germany")
    raise RuntimeError("AHDB 파일에서 Week ended 또는 Germany 열을 찾지 못했습니다.")


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


def _read_pdf_with_ocr(
    pdf_bytes: bytes,
    *,
    targeted: bool = False,
) -> tuple[list[dict[str, Any]], float, float]:
    """PDF 첫 페이지의 오른쪽 요약 카드를 OCR로 읽습니다.

    ``targeted``는 일반적인 뉴스라인 레이아웃의 소·돼지 카드 두 구간만 읽는다.
    카드가 예외적인 위치인 과거 호는 호출 측에서 기존 전체 범위로 다시 읽는다.
    """
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
        # 일반 호의 소고기 카드는 상단, 돼지고기 카드는 중단에 있다. 두 구간을
        # 우선 읽으면 기존 5회 OCR보다 요청 횟수와 이미지 면적을 모두 줄일 수 있다.
        # 레이아웃 예외는 targeted=False 재시도에서 기존 범위를 그대로 사용한다.
        segments = ((0.10, 0.26), (0.45, 0.61)) if targeted else (
            (0.0, 0.12),
            (0.12, 0.24),
            (0.24, 0.36),
            (0.36, 0.48),
            (0.48, 0.60),
        )
        for start_ratio, end_ratio in segments:
            crop = pymupdf.Rect(
                page.rect.width * 0.55,
                page.rect.height * start_ratio,
                page.rect.width,
                page.rect.height * end_ratio,
            )
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=crop, alpha=False)
            # PNG를 임시 파일로 저장했다가 다시 읽지 않고 메모리에서 바로 전달한다.
            # 뉴스라인은 정방향 PDF이므로 방향 분류 추론도 생략한다.
            result = _get_ocr()(pixmap.tobytes("png"), use_cls=False)
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
            match = re.fullmatch(r"\s*\.?\s*([01]\.\d{2})\s*", line["text"])
            if match:
                return float(match.group(1))

    # OCR가 '$0.95'의 달러 기호와 숫자 사이에 점을 잘못 추가해 '$.0.95'로
    # 인식하는 경우가 있다. 실제 가격 형식은 그대로 검증하되 이 표기만 보완한다.
    price_pattern = re.compile(r"\$\s*\.?\s*(\d+(?:\.\d+)?)")
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
        match = re.fullmatch(r"\s*\.?\s*([01]\.\d{2})\s*", line["text"])
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
