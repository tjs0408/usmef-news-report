"""기존 해외시장 엑셀 양식에 USMEF 수집값을 채웁니다."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Mapping, Sequence
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_ROOT / "work"
NODE_EXECUTABLE = os.environ.get("ARTIFACT_NODE", "node")
TEMPLATE_SCRIPT = WORK_DIR / "template_report.mjs"
EXCEL_UPDATE_SCRIPT = WORK_DIR / "update_report_excel.ps1"
SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
MARKET_SHEETS = (
    {"sheetName": "소-미국", "dateColumn": "EO", "currentColumn": "EQ", "revisionColumn": "ER", "priceColumn": "ES", "kgPriceColumn": "ET", "exchangeColumn": "EU", "wonPriceColumn": "EV", "market": "beef"},
    {"sheetName": "돼지-미국", "dateColumn": "FD", "currentColumn": "FF", "revisionColumn": "FG", "priceColumn": "FH", "kgPriceColumn": "FI", "exchangeColumn": "FJ", "wonPriceColumn": "FK", "market": "pork"},
)
EU_GERMANY_SHEET = {
    "sheetName": "돼지-EU(독일)",
    "dateColumn": "LH",
    "currentColumn": "LJ",
    "kgPriceColumn": "LK",
    "exchangeColumn": "LL",
    "wonPriceColumn": "LM",
    "wonKgPriceColumn": "LN",
    "market": "eu_pork_germany",
}
JAPAN_EGG_SHEET = {
    "sheetName": "계란-일본",
    "dateColumn": "V",
    "currentColumn": "Y",
    "exchangeColumn": "Z",
    "wonPriceColumn": "AA",
    "market": "japan_egg",
}
US_EGG_SHEET = {
    "sheetName": "계란-미국",
    "dateColumn": "X",
    "inventoryColumn": "Z",
    "priceColumn": "AB",
    "exchangeColumn": "AD",
    "market": "us_egg",
}
BRAZIL_CHICKEN_SHEET = {
    "sheetName": "닭-브라질",
    "dateColumn": "P",
    "currentColumn": "R",
    "exchangeColumn": "S",
    "wonPriceColumn": "T",
    "market": "brazil_chicken",
}
US_CHICKEN_SHEET = {
    "sheetName": "닭-미국",
    "dateColumn": "V",
    "slaughterColumn": "X",
    "currentColumn": "Z",
    # 그래프 양식은 닭-미국 데이터 표보다 4행 위에서 같은 주차가 시작된다.
    # 현재 양식의 2026YMD 열(F)에 Slug 3646의 Wtd Avg를 함께 기록한다.
    "graphSheetName": "미국 육계 그래프(WOG)",
    "graphColumn": "F",
    "graphRowOffset": -4,
    "market": "us_chicken",
}
AUSTRALIA_BEEF_SHEET = {
    "sheetName": "소-호주",
    "dateColumn": "EZ",
    "slaughterColumn": "FB",
    "thousandHeadColumn": "FC",
    "eyciColumn": "FD",
    "audPriceColumn": "FE",
    "exchangeColumn": "FF",
    "wonPriceColumn": "FG",
    "market": "australia_beef",
}


def find_pending_report_dates(template_path: Path, today: date) -> list[dict[str, object]]:
    """소·돼지-미국 시트의 최신 연속 미입력 주차만 찾습니다.

    양식 중간의 과거 공백(휴장·수동 보정 대기 등)은 다시 OCR하지 않는다.
    최신으로 이어진 빈 주차만 처리해 주간 현행화 요청의 PDF 수를 줄인다.
    """
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        pending: list[dict[str, object]] = []
        for config in MARKET_SHEETS:
            cell_values = _read_sheet_cell_values(archive, sheet_paths[config["sheetName"]])
            sheet_pending: list[dict[str, object]] = []
            for row in range(60, 7, -1):
                friday_serial = cell_values.get(f"{config['dateColumn']}{row}")
                current_slaughter = cell_values.get(f"{config['currentColumn']}{row}")
                if friday_serial is None:
                    continue
                friday = _excel_serial_to_date(friday_serial)
                report_date = friday + timedelta(days=5)
                if report_date > today:
                    continue
                if current_slaughter is not None:
                    break
                sheet_pending.append(
                    {
                        **config,
                        "row": row,
                        "reportDate": report_date.isoformat(),
                        "exchangeDate": friday.isoformat(),
                    }
                )
            pending.extend(reversed(sheet_pending))
    return pending


def find_pending_eu_germany_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """돼지-EU(독일) 양식에서 아직 입력되지 않은 과거 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[EU_GERMANY_SHEET["sheetName"]])
    pending: list[dict[str, object]] = []
    # 과거 휴장일 등으로 남아 있는 단일 공백은 보존하고, 가장 최근에 이어진
    # 새 주차 공백만 현행화한다.
    for row in range(59, 7, -1):
        week_ended_serial = cell_values.get(f"{EU_GERMANY_SHEET['dateColumn']}{row}")
        germany_price = cell_values.get(f"{EU_GERMANY_SHEET['currentColumn']}{row}")
        euro_exchange_rate = cell_values.get(f"{EU_GERMANY_SHEET['exchangeColumn']}{row}")
        if week_ended_serial is None or (germany_price is not None and euro_exchange_rate is not None):
            continue
        week_ended = _excel_serial_to_date(week_ended_serial)
        if week_ended <= today:
            pending.append(
                {
                    **EU_GERMANY_SHEET,
                    "row": row,
                    "weekEnded": week_ended.isoformat(),
                    "euroExchangeDate": week_ended.isoformat(),
                }
            )
    return pending


def find_pending_japan_egg_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """계란-일본 양식에서 도쿄 M란 기준치가 비어 있는 지난 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[JAPAN_EGG_SHEET["sheetName"]])

    pending: list[dict[str, object]] = []
    for row in range(6, 58):
        week_ended_serial = cell_values.get(f"{JAPAN_EGG_SHEET['dateColumn']}{row}")
        tokyo_m_price = cell_values.get(f"{JAPAN_EGG_SHEET['currentColumn']}{row}")
        if week_ended_serial is None or tokyo_m_price is not None:
            continue
        target_date = _excel_serial_to_date(week_ended_serial)
        if target_date <= today:
            pending.append(
                {
                    **JAPAN_EGG_SHEET,
                    "row": row,
                    "priceDate": target_date.isoformat(),
                    "exchangeDate": target_date.isoformat(),
                }
            )
    return pending


def find_pending_us_egg_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """계란-미국 양식에서 재고량 또는 Large 가격이 비어 있는 지난 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[US_EGG_SHEET["sheetName"]])

    pending: list[dict[str, object]] = []
    for row in range(6, 58):
        week_ended_serial = cell_values.get(f"{US_EGG_SHEET['dateColumn']}{row}")
        inventory = cell_values.get(f"{US_EGG_SHEET['inventoryColumn']}{row}")
        price = cell_values.get(f"{US_EGG_SHEET['priceColumn']}{row}")
        exchange_rate = cell_values.get(f"{US_EGG_SHEET['exchangeColumn']}{row}")
        if week_ended_serial is None or (inventory is not None and price is not None and exchange_rate is not None):
            continue
        week_ended = _excel_serial_to_date(week_ended_serial)
        if week_ended <= today:
            pending.append(
                {
                    **US_EGG_SHEET,
                    "row": row,
                    "weekEnded": week_ended.isoformat(),
                    "exchangeDate": week_ended.isoformat(),
                }
            )
    return pending


def find_pending_brazil_chicken_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """닭-브라질 양식에서 À vista R$/kg 또는 BRL 환율이 비어 있는 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[BRAZIL_CHICKEN_SHEET["sheetName"]])

    pending: list[dict[str, object]] = []
    for row in range(6, 58):
        week_ended_serial = cell_values.get(f"{BRAZIL_CHICKEN_SHEET['dateColumn']}{row}")
        cash_price = cell_values.get(f"{BRAZIL_CHICKEN_SHEET['currentColumn']}{row}")
        exchange_rate = cell_values.get(f"{BRAZIL_CHICKEN_SHEET['exchangeColumn']}{row}")
        if week_ended_serial is None or (cash_price is not None and exchange_rate is not None):
            continue
        week_ended = _excel_serial_to_date(week_ended_serial)
        if week_ended <= today:
            pending.append(
                {
                    **BRAZIL_CHICKEN_SHEET,
                    "row": row,
                    "weekEnded": week_ended.isoformat(),
                    "exchangeDate": week_ended.isoformat(),
                }
            )
    return pending


def find_pending_us_chicken_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """닭-미국 양식에서 USDA WOG 가격이 비어 있는 지난 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[US_CHICKEN_SHEET["sheetName"]])

    pending: list[dict[str, object]] = []
    for row in range(6, 58):
        week_ended_serial = cell_values.get(f"{US_CHICKEN_SHEET['dateColumn']}{row}")
        weekly_slaughter = cell_values.get(f"{US_CHICKEN_SHEET['slaughterColumn']}{row}")
        wog_price = cell_values.get(f"{US_CHICKEN_SHEET['currentColumn']}{row}")
        if week_ended_serial is None or (weekly_slaughter is not None and wog_price is not None):
            continue
        week_ended = _excel_serial_to_date(week_ended_serial)
        if week_ended <= today:
            pending.append({**US_CHICKEN_SHEET, "row": row, "weekEnded": week_ended.isoformat()})
    return pending


def find_pending_australia_beef_rows(template_path: Path, today: date) -> list[dict[str, object]]:
    """소-호주 양식에서 MLA 도축량·EYCI·AUD 환율이 비어 있는 지난 주차를 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        cell_values = _read_sheet_cell_values(archive, sheet_paths[AUSTRALIA_BEEF_SHEET["sheetName"]])

    pending: list[dict[str, object]] = []
    for row in range(59, 7, -1):
        week_ended_serial = cell_values.get(f"{AUSTRALIA_BEEF_SHEET['dateColumn']}{row}")
        slaughter_count = cell_values.get(f"{AUSTRALIA_BEEF_SHEET['slaughterColumn']}{row}")
        eyci = cell_values.get(f"{AUSTRALIA_BEEF_SHEET['eyciColumn']}{row}")
        exchange_rate = cell_values.get(f"{AUSTRALIA_BEEF_SHEET['exchangeColumn']}{row}")
        if week_ended_serial is None:
            continue
        if slaughter_count is not None and eyci is not None and exchange_rate is not None:
            if pending:
                break
            continue
        week_ended = _excel_serial_to_date(week_ended_serial)
        if week_ended + timedelta(days=1) <= today:
            pending.append(
                {
                    **AUSTRALIA_BEEF_SHEET,
                    "row": row,
                    "weekEnded": week_ended.isoformat(),
                    "exchangeDate": week_ended.isoformat(),
                }
            )
    return list(reversed(pending))


def write_market_data_to_template(
    template_path: Path,
    output_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    market_data: Sequence[Mapping[str, object]],
    exchange_rates: Mapping[date, float],
    eu_germany_rows: Sequence[Mapping[str, object]] = (),
    eu_germany_prices: Mapping[date, float] | None = None,
    eur_exchange_rates: Mapping[date, float] | None = None,
    japan_egg_rows: Sequence[Mapping[str, object]] = (),
    japan_egg_prices: Mapping[date, float] | None = None,
    jpy_exchange_rates: Mapping[date, float] | None = None,
    us_egg_rows: Sequence[Mapping[str, object]] = (),
    us_egg_data: Mapping[date, Mapping[str, float]] | None = None,
    brazil_chicken_rows: Sequence[Mapping[str, object]] = (),
    brazil_chicken_prices: Mapping[date, float] | None = None,
    brl_exchange_rates: Mapping[date, float] | None = None,
    us_chicken_rows: Sequence[Mapping[str, object]] = (),
    us_chicken_prices: Mapping[date, float] | None = None,
    australia_beef_rows: Sequence[Mapping[str, object]] = (),
    australia_beef_data: Mapping[date, Mapping[str, float]] | None = None,
    aud_exchange_rates: Mapping[date, float] | None = None,
    brazil_chicken_graph_prices: Mapping[date, float] | None = None,
) -> None:
    """수집값·환율을 입력하고, 다음 주 뉴스로 이전 주 도축두수를 정정합니다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = output_path.with_suffix(".pending.json")
    market_data_path = output_path.with_suffix(".market-data.json")
    serialized_data = {
        "marketData": [
            {
                "reportDate": item["구분"].isoformat(),
                "slaughterCount": item["도축두수"],
                "previousSlaughterCount": item["usda 수정"],
                "cutoutPrice": item["미국($/lb)"],
                "porkSlaughterCount": item["돼지 도축두수"],
                "porkPreviousSlaughterCount": item["돼지 usda 수정"],
                "porkCutoutPrice": item["돼지 미국($/lb)"],
            }
            for item in market_data
        ],
        "euGermanyPrices": [
            {"weekEnded": item.isoformat(), "germanyPrice": price}
            for item, price in (eu_germany_prices or {}).items()
        ],
        "japanEggPrices": [
            {"priceDate": item.isoformat(), "tokyoMPrice": price}
            for item, price in (japan_egg_prices or {}).items()
        ],
        "usEggData": [
            {
                "weekEnded": item.isoformat(),
                "weeklyInventory": values["weeklyInventory"],
                "largeAveragePrice": values["largeAveragePrice"],
            }
            for item, values in (us_egg_data or {}).items()
        ],
        "brazilChickenPrices": [
            {"weekEnded": item.isoformat(), "cashPrice": price}
            for item, price in (brazil_chicken_prices or {}).items()
        ],
        "brazilChickenGraphPrices": [
            {"priceDate": item.isoformat(), "cashPrice": price}
            for item, price in sorted((brazil_chicken_graph_prices or {}).items())
        ],
        "usChickenPrices": [
            {
                "weekEnded": item.isoformat(),
                "weeklySlaughter": values["weeklySlaughter"],
                "wtdAvg": values["wtdAvg"],
            }
            for item, values in (us_chicken_prices or {}).items()
        ],
        "australiaBeefData": [
            {
                "weekEnded": item.isoformat(),
                "slaughterCount": values["slaughterCount"],
                "eyci": values["eyci"],
            }
            for item, values in (australia_beef_data or {}).items()
        ],
    }
    serialized_pending_rows = [
        {
            **item,
            "exchangeRate": exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in pending_rows
    ] + [
        {
            **item,
            "euroExchangeRate": eur_exchange_rates[date.fromisoformat(str(item["euroExchangeDate"]))],
        }
        for item in eu_germany_rows
    ] + [
        {
            **item,
            "jpyExchangeRate": jpy_exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in japan_egg_rows
    ] + [
        {
            **item,
            "usdExchangeRate": exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in us_egg_rows
    ] + [
        {
            **item,
            "brlExchangeRate": brl_exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in brazil_chicken_rows
    ] + [
        dict(item)
        for item in us_chicken_rows
    ] + [
        {
            **item,
            "audExchangeRate": aud_exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in australia_beef_rows
    ]
    try:
        pending_path.write_text(json.dumps(serialized_pending_rows), encoding="utf-8")
        market_data_path.write_text(json.dumps(serialized_data), encoding="utf-8")
        _run_excel_update_script(template_path, output_path, pending_path, market_data_path)
    finally:
        pending_path.unlink(missing_ok=True)
        market_data_path.unlink(missing_ok=True)


def _run_excel_update_script(
    template_path: Path,
    output_path: Path,
    pending_path: Path,
    market_data_path: Path,
) -> None:
    """Microsoft Excel로 기준 양식을 열어 값만 갱신하고 안전하게 저장합니다."""
    if os.name != "nt":
        raise RuntimeError("이 양식은 Microsoft Excel이 설치된 Windows PC에서 생성해야 합니다.")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(EXCEL_UPDATE_SCRIPT),
        "-TemplatePath",
        str(template_path),
        "-OutputPath",
        str(output_path),
        "-PendingPath",
        str(pending_path),
        "-MarketDataPath",
        str(market_data_path),
    ]
    last_error: subprocess.CalledProcessError | None = None
    # Excel COM은 자동 저장·계산 직후 일시적으로 0x800A03EC을 낼 수 있다.
    # 같은 임시 원본을 한 번만 다시 열어 재시도하면 데이터 중복 없이 복구된다.
    for attempt in range(2):
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                # Windows PowerShell의 오류 메시지는 시스템 ANSI 코드페이지로 나온다.
                # cp949로 읽어야 실제 Excel COM 오류를 사용자에게 그대로 보여 줄 수 있다.
                encoding="cp949",
                errors="replace",
                timeout=120,
            )
            return
        except subprocess.CalledProcessError as error:
            last_error = error
            if attempt == 0:
                time.sleep(1)

    details = (last_error.stderr or last_error.stdout or "알 수 없는 오류").strip()
    raise RuntimeError(f"Excel 보고서를 저장하지 못했습니다. ({details})") from last_error


def _apply_market_data_to_template(
    output_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    market_data: Sequence[Mapping[str, object]],
    eu_germany_rows: Sequence[Mapping[str, object]],
    eu_germany_prices: Mapping[date, float],
) -> None:
    """기준 양식의 다른 구성 요소를 보존한 채 수집값 셀만 갱신합니다."""
    temporary_path = output_path.with_suffix(".cells.xlsx")
    with ZipFile(output_path, "r") as source:
        contents = {info.filename: source.read(info.filename) for info in source.infolist()}
        info_by_name = {info.filename: info for info in source.infolist()}
        sheet_paths = _find_sheet_paths(source)

    data_by_date = {item["구분"]: item for item in market_data}
    pending_by_sheet: dict[str, list[Mapping[str, object]]] = {}
    for item in [*pending_rows, *eu_germany_rows]:
        pending_by_sheet.setdefault(str(item["sheetName"]), []).append(item)

    for sheet_name, items in pending_by_sheet.items():
        worksheet_path = sheet_paths[sheet_name]
        worksheet = ElementTree.fromstring(contents[worksheet_path])
        for item in items:
            row = int(item["row"])
            if item.get("market") == "eu_pork_germany":
                germany_price = eu_germany_prices.get(date.fromisoformat(str(item["weekEnded"])))
                if germany_price is None:
                    continue
                _set_worksheet_number(worksheet, f"{item['currentColumn']}{row}", germany_price)
                _set_worksheet_formula(worksheet, f"{item['kgPriceColumn']}{row}", f"ROUND({item['currentColumn']}{row}/100,2)", round(germany_price / 100, 2))
                _set_worksheet_formula(worksheet, f"{item['wonPriceColumn']}{row}", f"{item['currentColumn']}{row}*{item['exchangeColumn']}{row}")
                _set_worksheet_formula(worksheet, f"{item['wonKgPriceColumn']}{row}", f"{item['wonPriceColumn']}{row}/100")
                for column in (item["currentColumn"], item["kgPriceColumn"], item["exchangeColumn"], item["wonPriceColumn"], item["wonKgPriceColumn"]):
                    _copy_nearest_cell_style(worksheet, str(column), row)
                continue

            report_date = date.fromisoformat(str(item["reportDate"]))
            data = data_by_date.get(report_date)
            if data is None:
                continue
            is_pork = item["market"] == "pork"
            slaughter_count = data["돼지 도축두수"] if is_pork else data["도축두수"]
            previous_slaughter_count = data["돼지 usda 수정"] if is_pork else data["usda 수정"]
            cutout_price = data["돼지 미국($/lb)"] if is_pork else data["미국($/lb)"]
            _set_worksheet_number(worksheet, f"{item['currentColumn']}{row}", float(slaughter_count))
            _clear_worksheet_cell_contents(worksheet, f"{item['revisionColumn']}{row}")
            _set_worksheet_number(worksheet, f"{item['priceColumn']}{row}", float(cutout_price))
            _set_worksheet_formula(
                worksheet,
                f"{item['kgPriceColumn']}{row}",
                f"{item['priceColumn']}{row}*2.20462",
                float(cutout_price) * 2.20462,
            )

            previous_row = row - 1
            recorded_previous = _worksheet_number(worksheet, f"{item['currentColumn']}{previous_row}")
            if previous_slaughter_count is not None and previous_slaughter_count != recorded_previous:
                _set_worksheet_number(worksheet, f"{item['currentColumn']}{previous_row}", float(previous_slaughter_count))
                if recorded_previous is not None:
                    _set_worksheet_number(worksheet, f"{item['revisionColumn']}{previous_row}", recorded_previous)
            for column in (item["currentColumn"], item["revisionColumn"], item["priceColumn"], item["kgPriceColumn"]):
                _copy_nearest_cell_style(worksheet, str(column), row)
        contents[worksheet_path] = ElementTree.tostring(worksheet, encoding="utf-8", xml_declaration=True)

    with ZipFile(temporary_path, "w", ZIP_DEFLATED) as target:
        for name, data in contents.items():
            target.writestr(info_by_name[name], data)
    temporary_path.replace(output_path)


def _run_template_script(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            [NODE_EXECUTABLE, str(TEMPLATE_SCRIPT), *arguments],
            cwd=WORK_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() if error.stderr else str(error)
        raise RuntimeError(f"엑셀 양식을 처리하지 못했습니다. ({details})") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"엑셀 양식을 처리하지 못했습니다. ({error})") from error
    return completed.stdout


def _find_sheet_paths(archive: ZipFile) -> dict[str, str]:
    """xlsx 내부에서 시트 이름과 worksheet XML 경로를 연결합니다."""
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.get("Id"): item.get("Target")
        for item in relationships.findall(f"{{{PACKAGE_RELATIONSHIP_NAMESPACE}}}Relationship")
    }
    paths: dict[str, str] = {}
    for sheet in workbook.findall(f"{{{SPREADSHEET_NAMESPACE}}}sheets/{{{SPREADSHEET_NAMESPACE}}}sheet"):
        relationship_id = sheet.get(f"{{{RELATIONSHIP_NAMESPACE}}}id")
        target = targets.get(relationship_id)
        if target is None:
            continue
        paths[sheet.get("name")] = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    return paths


def _read_sheet_cell_values(archive: ZipFile, sheet_path: str) -> dict[str, str]:
    """대상 범위 확인에 필요한 셀 값만 worksheet XML에서 읽습니다."""
    worksheet = ElementTree.fromstring(archive.read(sheet_path))
    values: dict[str, str] = {}
    for cell in worksheet.findall(f".//{{{SPREADSHEET_NAMESPACE}}}c"):
        value = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}v")
        if value is not None and value.text is not None:
            values[cell.get("r")] = value.text
    return values


def _excel_serial_to_date(value: str) -> date:
    return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()


def _set_opening_view(
    output_path: Path,
    template_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    exchange_rates: Mapping[date, float],
    eur_exchange_rates: Mapping[date, float],
) -> None:
    """환율·원화 환산값과, 각 시트의 마지막 현행화 위치를 설정합니다."""
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relationship_namespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_relationship_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    ElementTree.register_namespace("", namespace)
    temporary_path = output_path.with_suffix(".focus.xlsx")

    with ZipFile(output_path, "r") as source:
        contents = {info.filename: source.read(info.filename) for info in source.infolist()}
        info_by_name = {info.filename: info for info in source.infolist()}

    with ZipFile(template_path, "r") as template_archive:
        template_sheet_paths = _find_sheet_paths(template_archive)
        template_worksheet = ElementTree.fromstring(
            template_archive.read(template_sheet_paths[EU_GERMANY_SHEET["sheetName"]])
        )
        template_eu_sheet_views = template_worksheet.find(f"{{{namespace}}}sheetViews")

    workbook = ElementTree.fromstring(contents["xl/workbook.xml"])
    sheets = workbook.findall(f"{{{namespace}}}sheets/{{{namespace}}}sheet")
    relationships = ElementTree.fromstring(contents["xl/_rels/workbook.xml.rels"])
    relationship_targets = {
        item.get("Id"): item.get("Target")
        for item in relationships.findall(f"{{{package_relationship_namespace}}}Relationship")
    }
    focus_by_sheet: dict[str, tuple[str, str]] = {}
    for item in pending_rows:
        # 이 시트는 B8 고정 창과 넓은 연도별 영역을 함께 사용한다. topLeftCell을
        # 최신 열로 강제하면 Excel의 분할 창이 흔들릴 수 있어 원래 화면을 보존한다.
        if item.get("market") == "eu_pork_germany":
            continue
        sheet_name = str(item["sheetName"])
        row = int(item["row"])
        date_column = str(item["dateColumn"])
        previous_focus = focus_by_sheet.get(sheet_name)
        if previous_focus is None or row > int(previous_focus[1][len(date_column) :]):
            focus_by_sheet[sheet_name] = (f"{date_column}{max(8, row - 1)}", f"{date_column}{row}")

    # 원본 양식에 저장된 추가 workbookView는 Excel에서 동일 파일을 :1, :2 창으로
    # 열게 한다. 생성본은 첫 번째 보기만 유지해 한 통합문서 창으로 통일한다.
    book_views = workbook.find(f"{{{namespace}}}bookViews")
    if book_views is None:
        book_views = ElementTree.Element(f"{{{namespace}}}bookViews")
        workbook.insert(0, book_views)
    workbook_views = book_views.findall(f"{{{namespace}}}workbookView")
    if workbook_views:
        workbook_view = workbook_views[0]
        for extra_view in workbook_views[1:]:
            book_views.remove(extra_view)
    else:
        workbook_view = ElementTree.SubElement(book_views, f"{{{namespace}}}workbookView")

    if focus_by_sheet:
        active_sheet_name = "소-미국" if "소-미국" in focus_by_sheet else next(iter(focus_by_sheet))
        target_sheet_index = next(index for index, sheet in enumerate(sheets) if sheet.get("name") == active_sheet_name)
        workbook_view.set("activeTab", str(target_sheet_index))
    contents["xl/workbook.xml"] = ElementTree.tostring(workbook, encoding="utf-8", xml_declaration=True)

    for sheet in sheets:
        sheet_name = sheet.get("name")
        focus = focus_by_sheet.get(sheet_name)
        pending_for_sheet = [item for item in pending_rows if item["sheetName"] == sheet_name]
        if focus is None and not pending_for_sheet:
            continue
        relationship_target = relationship_targets[sheet.get(f"{{{relationship_namespace}}}id")]
        sheet_path = relationship_target.lstrip("/") if relationship_target.startswith("/") else f"xl/{relationship_target}"
        worksheet = ElementTree.fromstring(contents[sheet_path])
        for item in pending_for_sheet:
            if item.get("market") == "eu_pork_germany":
                exchange_date = date.fromisoformat(str(item["euroExchangeDate"]))
                euro_exchange_rate = eur_exchange_rates[exchange_date]
                row = int(item["row"])
                germany_price = _worksheet_number(worksheet, f"{item['currentColumn']}{row}")
                _set_worksheet_number(worksheet, f"{item['exchangeColumn']}{row}", euro_exchange_rate)
                if germany_price is not None:
                    _set_worksheet_number(worksheet, f"{item['wonPriceColumn']}{row}", germany_price * euro_exchange_rate)
                    _set_worksheet_number(worksheet, f"{item['wonKgPriceColumn']}{row}", germany_price * euro_exchange_rate / 100)
                # 새로 생성된 셀도 바로 위 기존 행의 테두리·채우기·정렬을 사용한다.
                # 지육가격 표의 가로 틀이 이어져 보이도록 열마다 서식을 복사한다.
                for column in (
                    item["currentColumn"],
                    item["kgPriceColumn"],
                    item["exchangeColumn"],
                    item["wonPriceColumn"],
                    item["wonKgPriceColumn"],
                ):
                    _copy_nearest_cell_style(worksheet, str(column), row)
                continue
            if "exchangeDate" not in item:
                continue
            exchange_date = date.fromisoformat(str(item["exchangeDate"]))
            exchange_rate = exchange_rates[exchange_date]
            row = int(item["row"])
            kg_price = _worksheet_number(worksheet, f"{item['kgPriceColumn']}{row}")
            if kg_price is None:
                raise RuntimeError(f"{sheet_name} {row}행의 미국($/kg) 값을 계산하지 못했습니다.")
            _set_worksheet_number(worksheet, f"{item['exchangeColumn']}{row}", exchange_rate)
            _set_worksheet_number(worksheet, f"{item['wonPriceColumn']}{row}", kg_price * exchange_rate)

        if focus is not None:
            sheet_views = worksheet.find(f"{{{namespace}}}sheetViews")
            if sheet_views is None:
                sheet_views = ElementTree.Element(f"{{{namespace}}}sheetViews")
                sheet_format = worksheet.find(f"{{{namespace}}}sheetFormatPr")
                sheet_view_index = list(worksheet).index(sheet_format) if sheet_format is not None else 0
                worksheet.insert(sheet_view_index, sheet_views)
            sheet_view = sheet_views.find(f"{{{namespace}}}sheetView")
            if sheet_view is None:
                sheet_view = ElementTree.SubElement(sheet_views, f"{{{namespace}}}sheetView")
            sheet_view.set("workbookViewId", "0")
            sheet_view.set("topLeftCell", focus[0])
            selection = sheet_view.find(f"{{{namespace}}}selection")
            if selection is None:
                selection = ElementTree.SubElement(sheet_view, f"{{{namespace}}}selection")
            selection.set("activeCell", focus[1])
            selection.set("sqref", focus[1])
        elif sheet_name == EU_GERMANY_SHEET["sheetName"] and template_eu_sheet_views is not None:
            current_sheet_views = worksheet.find(f"{{{namespace}}}sheetViews")
            if current_sheet_views is not None:
                worksheet.remove(current_sheet_views)
            sheet_format = worksheet.find(f"{{{namespace}}}sheetFormatPr")
            sheet_view_index = list(worksheet).index(sheet_format) if sheet_format is not None else 0
            original_sheet_views = ElementTree.fromstring(
                ElementTree.tostring(template_eu_sheet_views, encoding="utf-8")
            )
            worksheet.insert(sheet_view_index, original_sheet_views)
        contents[sheet_path] = ElementTree.tostring(worksheet, encoding="utf-8", xml_declaration=True)

    with ZipFile(temporary_path, "w", ZIP_DEFLATED) as target:
        for name, data in contents.items():
            target.writestr(info_by_name[name], data)

    temporary_path.replace(output_path)


def _worksheet_number(worksheet: ElementTree.Element, reference: str) -> float | None:
    """xlsx 워크시트에서 숫자 셀의 현재 값을 읽습니다."""
    cell = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{reference}']")
    if cell is None:
        return None
    value = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}v")
    if value is None or value.text is None:
        return None
    try:
        return float(value.text)
    except ValueError:
        return None


def _set_worksheet_number(worksheet: ElementTree.Element, reference: str, value: float) -> None:
    """기존 숫자 셀의 캐시 값을 갱신합니다. 양식의 서식·수식은 보존합니다."""
    cell = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{reference}']")
    if cell is None:
        cell = _create_worksheet_cell(worksheet, reference)
    cell.attrib.pop("t", None)
    value_node = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}v")
    if value_node is None:
        value_node = ElementTree.SubElement(cell, f"{{{SPREADSHEET_NAMESPACE}}}v")
    value_node.text = str(value)


def _set_worksheet_formula(
    worksheet: ElementTree.Element,
    reference: str,
    formula: str,
    cached_value: float | None = None,
) -> None:
    """수식과 선택적 계산 캐시를 입력하면서 기존 서식을 보존합니다."""
    cell = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{reference}']")
    if cell is None:
        cell = _create_worksheet_cell(worksheet, reference)
    cell.attrib.pop("t", None)
    formula_node = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}f")
    if formula_node is None:
        formula_node = ElementTree.Element(f"{{{SPREADSHEET_NAMESPACE}}}f")
        value_node = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}v")
        insert_index = list(cell).index(value_node) if value_node is not None else len(cell)
        cell.insert(insert_index, formula_node)
    formula_node.text = formula
    if cached_value is not None:
        _set_worksheet_number(worksheet, reference, cached_value)


def _clear_worksheet_cell_contents(worksheet: ElementTree.Element, reference: str) -> None:
    """값·수식만 비우고 셀 서식은 그대로 유지합니다."""
    cell = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{reference}']")
    if cell is None:
        return
    for tag_name in ("f", "v", "is"):
        node = cell.find(f"{{{SPREADSHEET_NAMESPACE}}}{tag_name}")
        if node is not None:
            cell.remove(node)
    cell.attrib.pop("t", None)


def _copy_nearest_cell_style(worksheet: ElementTree.Element, column: str, row_number: int) -> None:
    """새 데이터 셀에 바로 위 표 행의 완성된 표시 서식을 적용합니다."""
    target = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{column}{row_number}']")
    if target is None:
        return
    for source_row in range(row_number - 1, 7, -1):
        source = worksheet.find(f".//{{{SPREADSHEET_NAMESPACE}}}c[@r='{column}{source_row}']")
        if source is None or source.get("s") is None:
            continue
        target.set("s", source.get("s"))
        return


def _create_worksheet_cell(worksheet: ElementTree.Element, reference: str) -> ElementTree.Element:
    """비어 있어 내보내기 과정에서 사라진 양식 셀을 같은 행에 다시 만듭니다."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", reference)
    if match is None:
        raise RuntimeError(f"잘못된 Excel 셀 주소입니다: {reference}")
    column, row_number = match.groups()
    sheet_data = worksheet.find(f"{{{SPREADSHEET_NAMESPACE}}}sheetData")
    if sheet_data is None:
        raise RuntimeError("업로드한 양식에서 셀 데이터를 찾지 못했습니다.")
    row = sheet_data.find(f"{{{SPREADSHEET_NAMESPACE}}}row[@r='{row_number}']")
    if row is None:
        raise RuntimeError(f"업로드한 양식에서 {row_number}행을 찾지 못했습니다.")
    cell = ElementTree.Element(f"{{{SPREADSHEET_NAMESPACE}}}c", {"r": reference})
    target_column_number = _excel_column_number(column)
    for index, existing_cell in enumerate(list(row)):
        existing_reference = existing_cell.get("r", "")
        existing_column = "".join(character for character in existing_reference if character.isalpha())
        if existing_column and _excel_column_number(existing_column) > target_column_number:
            row.insert(index, cell)
            return cell
    row.append(cell)
    return cell


def _excel_column_number(column: str) -> int:
    result = 0
    for character in column:
        result = result * 26 + ord(character) - ord("A") + 1
    return result
