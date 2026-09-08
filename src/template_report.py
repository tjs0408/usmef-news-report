"""기존 해외시장 엑셀 양식에 USMEF 수집값을 채웁니다."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping, Sequence
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_ROOT / "work"
NODE_EXECUTABLE = os.environ.get("ARTIFACT_NODE", "node")
TEMPLATE_SCRIPT = WORK_DIR / "template_report.mjs"
SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
MARKET_SHEETS = (
    {"sheetName": "소-미국", "dateColumn": "EO", "currentColumn": "EQ", "revisionColumn": "ER", "priceColumn": "ES", "kgPriceColumn": "ET", "exchangeColumn": "EU", "wonPriceColumn": "EV", "market": "beef"},
    {"sheetName": "돼지-미국", "dateColumn": "FD", "currentColumn": "FF", "revisionColumn": "FG", "priceColumn": "FH", "kgPriceColumn": "FI", "exchangeColumn": "FJ", "wonPriceColumn": "FK", "market": "pork"},
)


def find_pending_report_dates(template_path: Path, today: date) -> list[dict[str, object]]:
    """도축두수 칸이 비어 있고 발행일이 지난 양식 행을 빠르게 찾습니다."""
    with ZipFile(template_path, "r") as archive:
        sheet_paths = _find_sheet_paths(archive)
        pending: list[dict[str, object]] = []
        for config in MARKET_SHEETS:
            cell_values = _read_sheet_cell_values(archive, sheet_paths[config["sheetName"]])
            for row in range(8, 61):
                friday_serial = cell_values.get(f"{config['dateColumn']}{row}")
                current_slaughter = cell_values.get(f"{config['currentColumn']}{row}")
                if friday_serial is None or current_slaughter is not None:
                    continue
                friday = _excel_serial_to_date(friday_serial)
                report_date = friday + timedelta(days=5)
                if report_date <= today:
                    pending.append(
                        {
                            **config,
                            "row": row,
                            "reportDate": report_date.isoformat(),
                            "exchangeDate": friday.isoformat(),
                        }
                    )
    return pending


def write_market_data_to_template(
    template_path: Path,
    output_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    market_data: Sequence[Mapping[str, object]],
    exchange_rates: Mapping[date, float],
) -> None:
    """수집값·환율을 입력하고, 다음 주 뉴스로 이전 주 도축두수를 정정합니다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = output_path.with_suffix(".pending.json")
    market_data_path = output_path.with_suffix(".market-data.json")
    serialized_data = [
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
    ]
    serialized_pending_rows = [
        {
            **item,
            "exchangeRate": exchange_rates[date.fromisoformat(str(item["exchangeDate"]))],
        }
        for item in pending_rows
    ]
    try:
        pending_path.write_text(json.dumps(serialized_pending_rows), encoding="utf-8")
        market_data_path.write_text(json.dumps(serialized_data), encoding="utf-8")
        _run_template_script(
            "fill",
            str(template_path),
            str(output_path),
            str(pending_path),
            str(market_data_path),
        )
        _set_opening_view(output_path, pending_rows, exchange_rates)
    finally:
        pending_path.unlink(missing_ok=True)
        market_data_path.unlink(missing_ok=True)


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
    pending_rows: Sequence[Mapping[str, object]],
    exchange_rates: Mapping[date, float],
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

    workbook = ElementTree.fromstring(contents["xl/workbook.xml"])
    sheets = workbook.findall(f"{{{namespace}}}sheets/{{{namespace}}}sheet")
    relationships = ElementTree.fromstring(contents["xl/_rels/workbook.xml.rels"])
    relationship_targets = {
        item.get("Id"): item.get("Target")
        for item in relationships.findall(f"{{{package_relationship_namespace}}}Relationship")
    }
    focus_by_sheet: dict[str, tuple[str, str]] = {}
    for item in pending_rows:
        sheet_name = str(item["sheetName"])
        row = int(item["row"])
        date_column = str(item["dateColumn"])
        previous_focus = focus_by_sheet.get(sheet_name)
        if previous_focus is None or row > int(previous_focus[1][len(date_column) :]):
            focus_by_sheet[sheet_name] = (f"{date_column}{max(8, row - 1)}", f"{date_column}{row}")

    active_sheet_name = "소-미국" if "소-미국" in focus_by_sheet else next(iter(focus_by_sheet))
    target_sheet_index = next(index for index, sheet in enumerate(sheets) if sheet.get("name") == active_sheet_name)

    book_views = workbook.find(f"{{{namespace}}}bookViews")
    if book_views is None:
        book_views = ElementTree.Element(f"{{{namespace}}}bookViews")
        workbook.insert(0, book_views)
    workbook_view = book_views.find(f"{{{namespace}}}workbookView")
    if workbook_view is None:
        workbook_view = ElementTree.SubElement(book_views, f"{{{namespace}}}workbookView")
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
            else:
                worksheet.remove(sheet_views)
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
