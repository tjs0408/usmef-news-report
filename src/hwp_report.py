"""현행화된 Excel 값을 한글(HWP) 주간 보고서 표에 옮깁니다.

한글 원본에는 표 셀을 식별하는 필드가 없어서, 현재 제공된 양식의 고정된
표 순서와 셀 좌표를 사용합니다. 본 모듈은 문장·그래프·제목은 전혀 다루지
않고, 8개 수급/가격 표의 날짜와 수치 셀만 갱신합니다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Lock
from typing import Any, Iterable

from .xlsx_values import read_cached_sheets


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_TEMPLATE_PATH = PROJECT_ROOT / "report_template" / "weekly_overseas_market_report_table_template.hwp"
HWP_UPDATE_SCRIPT = PROJECT_ROOT / "work" / "update_hwp_table_report.ps1"
WINDOWS_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

# 한글 COM 자동화는 같은 프로세스에서 동시에 실행하면 Hwp.exe가 멈출 수 있다.
HWP_AUTOMATION_LOCK = Lock()


class HwpReportError(RuntimeError):
    """한글 보고서 표 현행화가 불가능할 때 사용합니다."""


# tableIndex는 HWP 문서 안의 표(0부터)의 순서다. Excel의 report 두 시트는
# 8열 단위의 주차 블록을 쓰며, 블록 시작열+2~+6이 각각 전년/전주/이번 주/
# 전주 대비/전년 대비 값이다.
_TABLE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "tableIndex": 1,
        "sheet": "report",
        "dateRow": 213,
        "metrics": ((4, 214, "integer", True), (5, 215, "decimal2", True), (6, 216, "integer", False)),
    },
    {
        "tableIndex": 2,
        "sheet": "report",
        "dateRow": 220,
        "metrics": ((4, 221, "integer", True), (5, 222, "decimal2", True), (6, 223, "integer", False)),
    },
    {
        "tableIndex": 4,
        "sheet": "report",
        "dateRow": 227,
        "metrics": ((4, 228, "integer", True), (5, 229, "decimal2", True), (6, 230, "integer", False)),
    },
    {
        "tableIndex": 5,
        "sheet": "report",
        "dateRow": 234,
        # 독일 돼지고기 가격은 원천 발표가 다른 항목보다 약 1주 늦다.
        # 따라서 한글 표에는 보고 주차가 아닌 직전 주차의 3개 비교열을 사용한다.
        "reportDateWeekOffset": -1,
        "metrics": ((4, 235, "decimal2", True), (5, 236, "integer", False)),
    },
    {
        "tableIndex": 8,
        "sheet": "report_육계계란",
        "dateRow": 66,
        "metrics": ((4, 67, "integer", True), (5, 68, "decimal2", True), (6, 69, "integer", False)),
    },
    {
        "tableIndex": 9,
        "sheet": "report_육계계란",
        "dateRow": 73,
        "metrics": ((4, 74, "decimal2", True), (5, 75, "integer", False)),
    },
    {
        "tableIndex": 11,
        "sheet": "report_육계계란",
        "dateRow": 79,
        "metrics": ((4, 80, "integer", True), (5, 81, "decimal2", True), (6, 82, "integer", False)),
    },
    {
        "tableIndex": 12,
        "sheet": "report_육계계란",
        "dateRow": 86,
        "metrics": ((4, 87, "integer", True), (5, 88, "integer", False)),
    },
)

_REPORT_DATE_ROWS = {"report": 209, "report_육계계란": 62}
_REPORT_DATE_PATTERN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def latest_thursday(today: date | None = None) -> date:
    """Excel report 시트와 동일하게 가장 최근 목요일을 보고일자로 계산합니다."""
    reference = today or date.today()
    return reference - timedelta(days=(reference.weekday() - 3) % 7)


def build_hwp_table_payload(excel_path: Path, report_date: date | None = None) -> dict[str, object]:
    """HWP 표의 갱신 좌표와 표시 문자열을 Excel에서 만듭니다.

    Excel COM 저장 단계에서 계산·저장한 수식 결과만 읽는다. 표에 필요한 두
    시트·행만 ZIP에서 읽어, 모든 시트의 셀·스타일·그래프 파싱을 생략한다.
    이 함수는 Excel 파일을 수정하지 않는다.
    """
    preferred_date = report_date or latest_thursday()
    try:
        rows_by_sheet = {sheet: {row} for sheet, row in _REPORT_DATE_ROWS.items()}
        for section in _TABLE_SECTIONS:
            rows_by_sheet[section["sheet"]].add(section["dateRow"])
            rows_by_sheet[section["sheet"]].update(metric[1] for metric in section["metrics"])
        workbook = read_cached_sheets(excel_path, rows_by_sheet)
    except Exception as error:  # pragma: no cover - openpyxl 메시지는 환경별로 다름
        raise HwpReportError(f"현행화된 Excel 파일을 읽지 못했습니다. ({error})") from error

    try:
        target_date = _select_report_date(workbook, preferred_date)
        starts = {
            sheet_name: _find_report_block_start(workbook[sheet_name], _REPORT_DATE_ROWS[sheet_name], target_date)
            for sheet_name in _REPORT_DATE_ROWS
        }
        tables = []
        for section in _TABLE_SECTIONS:
            week_offset = int(section.get("reportDateWeekOffset", 0))
            section_date = target_date + timedelta(weeks=week_offset)
            start_column = (
                starts[section["sheet"]]
                if week_offset == 0
                else _find_report_block_start(
                    workbook[section["sheet"]],
                    _REPORT_DATE_ROWS[section["sheet"]],
                    section_date,
                )
            )
            tables.append(_build_section_cells(workbook[section["sheet"]], start_column, section))
    except KeyError as error:
        raise HwpReportError(f"Excel 양식에서 필요한 보고서 시트를 찾지 못했습니다. ({error})") from error

    return {
        "reportDate": target_date.isoformat(),
        # 제공된 한글 양식의 제목 날짜 표기는 '(9.10.)' 형식이다.
        # 문서 안의 표·본문 날짜와 구분해 상단 제목에만 사용한다.
        "titleDateLabel": f"({target_date.month}.{target_date.day}.)",
        "tables": tables,
    }


def write_hwp_table_report(
    excel_path: Path,
    output_path: Path,
    report_date: date | None = None,
    template_path: Path = REPORT_TEMPLATE_PATH,
) -> dict[str, object]:
    """한글 양식의 표 데이터만 갱신해 새 HWP 파일로 저장합니다.

    원본 양식은 열거나 저장 대상으로 사용하지 않는다. PowerShell 스크립트가
    임시 ASCII 경로에 복사본을 만든 뒤, 검증을 마친 결과만 ``output_path``로
    옮긴다.
    """
    if not template_path.is_file():
        raise HwpReportError(f"한글 보고서 양식을 찾지 못했습니다. ({template_path.name})")
    if not HWP_UPDATE_SCRIPT.is_file():
        raise HwpReportError("한글 보고서 갱신 스크립트를 찾지 못했습니다.")
    if not WINDOWS_POWERSHELL.is_file():
        raise HwpReportError("Windows PowerShell을 찾지 못했습니다. 한글 표 현행화는 Windows에서만 지원합니다.")

    payload = build_hwp_table_payload(excel_path, report_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="hwp_table_payload_", suffix=".json", dir=output_path.parent)
    try:
        with open(descriptor, "w", encoding="utf-8", closefd=True) as payload_file:
            json.dump(payload, payload_file, ensure_ascii=False)

        command = [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HWP_UPDATE_SCRIPT),
            "-TemplatePath",
            str(template_path),
            "-PayloadPath",
            temporary_name,
            "-OutputPath",
            str(output_path),
        ]
        with HWP_AUTOMATION_LOCK:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=150,
                check=False,
            )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise HwpReportError(f"한글 표를 저장하지 못했습니다. ({detail or '알 수 없는 오류'})")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise HwpReportError("한글 표 현행화 결과 파일을 만들지 못했습니다.")
    except subprocess.TimeoutExpired as error:
        raise HwpReportError("한글 표 현행화 시간이 초과되었습니다. 한글 프로그램이 열려 있는지 확인해 주세요.") from error
    finally:
        Path(temporary_name).unlink(missing_ok=True)

    return payload


def _find_report_block_start(worksheet: Any, row: int, target_date: date) -> int:
    """보고일자 셀에서 8열 주차 블록의 시작 열을 찾습니다."""
    matching_columns: list[int] = []
    for column in range(1, worksheet.max_column + 1):
        value = worksheet.cell(row, column).value
        if not isinstance(value, str):
            continue
        match = _REPORT_DATE_PATTERN.search(value)
        if not match:
            continue
        cell_date = date(*(int(match.group(index)) for index in range(1, 4)))
        if cell_date == target_date:
            matching_columns.append(column)

    if not matching_columns:
        raise HwpReportError(
            f"Excel의 {worksheet.title} 시트에서 보고일자 "
            f"{target_date.year}-{target_date.month}-{target_date.day} 주차 표를 찾지 못했습니다."
        )
    return matching_columns[-1]


def _select_report_date(workbook: Any, preferred_date: date) -> date:
    """두 요약 시트에 공통으로 있는 가장 최신 보고일자를 선택합니다.

    업로드 파일이 이미 완성된 파일이라 새 수집 대상이 없을 수도 있다. 이때도
    현재 날짜보다 늦지 않은 가장 최신 주차 표를 HWP에 반영할 수 있어야 한다.
    """
    sheet_dates: list[set[date]] = []
    for sheet_name, row in _REPORT_DATE_ROWS.items():
        worksheet = workbook[sheet_name]
        dates: set[date] = set()
        for column in range(1, worksheet.max_column + 1):
            value = worksheet.cell(row, column).value
            if not isinstance(value, str):
                continue
            match = _REPORT_DATE_PATTERN.search(value)
            if match:
                dates.add(date(*(int(match.group(index)) for index in range(1, 4))))
        sheet_dates.append(dates)

    common_dates = set.intersection(*sheet_dates) if sheet_dates else set()
    eligible_dates = [candidate for candidate in common_dates if candidate <= preferred_date]
    if not eligible_dates:
        raise HwpReportError(
            f"한글 표에 반영할 보고일자를 찾지 못했습니다. "
            f"(기준일: {preferred_date.year}-{preferred_date.month}-{preferred_date.day})"
        )
    return max(eligible_dates)


def _build_section_cells(worksheet: Any, start_column: int, section: dict[str, Any]) -> dict[str, object]:
    cells: list[dict[str, object]] = []
    # 2025 동일 주 / 2026 전주 / 2026 이번 주의 주차 라벨
    for table_column, source_offset in ((2, 2), (3, 3), (4, 4)):
        cells.append(
            {
                "row": 3,
                "column": table_column,
                "value": _display_text(worksheet.cell(section["dateRow"], start_column + source_offset).value, "text"),
            }
        )

    for table_row, source_row, display_format, has_comparisons in section["metrics"]:
        for table_column, source_offset in ((2, 2), (3, 3), (4, 4)):
            cells.append(
                {
                    "row": table_row,
                    "column": table_column,
                    "value": _display_text(worksheet.cell(source_row, start_column + source_offset).value, display_format),
                }
            )
        if has_comparisons:
            for table_column, source_offset in ((5, 5), (6, 6)):
                comparison_value = worksheet.cell(source_row, start_column + source_offset).value
                cells.append(
                    {
                        "row": table_row,
                        "column": table_column,
                        "value": _display_text(comparison_value, "percent"),
                        # 한글 원본 양식의 기존 색상 규칙을 그대로 사용한다.
                        # 양수=빨강, 음수=파랑, 0 또는 빈 값=검정.
                        "comparisonColor": _comparison_color(comparison_value),
                    }
                )
    return {"tableIndex": section["tableIndex"], "cells": cells}


def _display_text(value: object, display_format: str) -> str:
    """Excel의 계산값을 한글 표에 보일 문자열로 바꿉니다."""
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.startswith("#"):
            return ""
        if display_format == "text":
            return stripped
        try:
            value = Decimal(stripped.replace(",", ""))
        except InvalidOperation:
            return ""

    if display_format == "text":
        return str(value).strip()
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    if not numeric.is_finite():
        return ""

    if display_format == "integer":
        rounded = numeric.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{rounded:,}"
    if display_format == "decimal2":
        rounded = numeric.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{rounded:.2f}"
    if display_format == "percent":
        rounded = (numeric * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if rounded == 0:
            rounded = Decimal("0.0")
        return f"{rounded:.1f}%"
    raise ValueError(f"지원하지 않는 HWP 표시 형식입니다: {display_format}")


def _comparison_color(value: object) -> str:
    """한글 표에 *표시되는* 전주·전년 대비 값의 글자색을 반환합니다."""
    if value is None:
        return "black"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.startswith("#"):
            return "black"
        try:
            # Excel 계산값은 -0.014처럼 비율로 들어오고, 텍스트 값은 -1.4%처럼
            # 표시 단위로 들어올 수 있다. 두 경우 모두 표시값 기준으로 판정한다.
            value = Decimal(stripped.replace(",", "").replace("%", ""))
            if "%" in stripped:
                value /= Decimal("100")
        except InvalidOperation:
            return "black"
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "black"
    if not numeric.is_finite():
        return "black"
    # 한글 표는 소수 첫째 자리 %로 보여준다. 원본 계산값이 -0.04%여도 표에
    # '-0.0%'가 아닌 '0.0%'로 보이는 경우에는 색도 검정이어야 한다.
    displayed_percent = (numeric * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if displayed_percent == 0:
        return "black"
    return "red" if displayed_percent > 0 else "blue"
