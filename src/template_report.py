"""기존 해외시장 엑셀 양식에 USMEF 수집값을 채웁니다."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_ROOT / "work"
NODE_EXECUTABLE = os.environ.get("ARTIFACT_NODE", "node")
TEMPLATE_SCRIPT = WORK_DIR / "template_report.mjs"


def find_pending_report_dates(template_path: Path, today: date) -> list[dict[str, object]]:
    """도축두수 칸이 비어 있고 발행일이 지난 양식 행을 찾습니다."""
    result = _run_template_script("pending", str(template_path), today.isoformat())
    return json.loads(result)


def write_market_data_to_template(
    template_path: Path,
    output_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    market_data: Sequence[Mapping[str, object]],
) -> None:
    """수집값을 소-미국 탭에 쓰고, 전 주 값이 같으면 USDA 수정 칸을 비웁니다."""
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
    try:
        pending_path.write_text(json.dumps(list(pending_rows)), encoding="utf-8")
        market_data_path.write_text(json.dumps(serialized_data), encoding="utf-8")
        _run_template_script(
            "fill",
            str(template_path),
            str(output_path),
            str(pending_path),
            str(market_data_path),
        )
        _set_opening_view(output_path)
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
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"엑셀 양식을 처리하지 못했습니다. ({error})") from error
    return completed.stdout


def _set_opening_view(output_path: Path) -> None:
    """파일을 열면 소-미국 탭의 새 입력 위치부터 보이도록 설정합니다."""
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
    target_sheet_index, target_sheet = next(
        (index, sheet) for index, sheet in enumerate(sheets) if sheet.get("name") == "소-미국"
    )
    relationship_id = target_sheet.get(f"{{{relationship_namespace}}}id")
    relationships = ElementTree.fromstring(contents["xl/_rels/workbook.xml.rels"])
    relationship = next(
        item
        for item in relationships.findall(f"{{{package_relationship_namespace}}}Relationship")
        if item.get("Id") == relationship_id
    )
    relationship_target = relationship.get("Target")
    sheet_path = relationship_target.lstrip("/") if relationship_target.startswith("/") else f"xl/{relationship_target}"

    book_views = workbook.find(f"{{{namespace}}}bookViews")
    if book_views is None:
        book_views = ElementTree.Element(f"{{{namespace}}}bookViews")
        workbook.insert(0, book_views)
    workbook_view = book_views.find(f"{{{namespace}}}workbookView")
    if workbook_view is None:
        workbook_view = ElementTree.SubElement(book_views, f"{{{namespace}}}workbookView")
    workbook_view.set("activeTab", str(target_sheet_index))
    contents["xl/workbook.xml"] = ElementTree.tostring(workbook, encoding="utf-8", xml_declaration=True)

    worksheet = ElementTree.fromstring(contents[sheet_path])
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
    sheet_view.set("topLeftCell", "EO41")
    selection = sheet_view.find(f"{{{namespace}}}selection")
    if selection is None:
        selection = ElementTree.SubElement(sheet_view, f"{{{namespace}}}selection")
    selection.set("activeCell", "EO41")
    selection.set("sqref", "EO41")
    contents[sheet_path] = ElementTree.tostring(worksheet, encoding="utf-8", xml_declaration=True)

    with ZipFile(temporary_path, "w", ZIP_DEFLATED) as target:
        for name, data in contents.items():
            target.writestr(info_by_name[name], data)

    temporary_path.replace(output_path)
