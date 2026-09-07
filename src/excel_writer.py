"""주간 해외 동향 데이터를 Excel 파일로 저장합니다."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


HEADERS = ("구분", "도축두수", "미국($/lb)")


def write_market_data_to_excel(market_data: Sequence[Mapping[str, object]], output_path: Path) -> None:
    """소고기 주간 지표를 날짜 내림차순의 지정된 세 열 구조로 저장합니다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "주간 해외 동향"
    worksheet.append(HEADERS)
    for item in market_data:
        worksheet.append([item[header] for header in HEADERS])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in worksheet.iter_rows(min_row=2, max_col=len(HEADERS)):
        row[0].number_format = "yyyy-mm-dd"
        row[1].number_format = '#,##0" 천두"'
        row[2].number_format = "0.00"
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.column_dimensions["A"].width = 16
    worksheet.column_dimensions["B"].width = 16
    worksheet.column_dimensions["C"].width = 18
    worksheet.row_dimensions[1].height = 22
    workbook.save(output_path)
