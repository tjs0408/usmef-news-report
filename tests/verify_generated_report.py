"""Optional XML QA of actual generated Excel, against a separate baseline file."""
from datetime import date
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl.utils.cell import get_column_letter, range_boundaries
from src import hwp_report as h
from src.template_report import _find_sheet_paths
from src.xlsx_values import read_cached_sheets


def verify(path: Path, baseline: Path):
    payload = h.build_hwp_table_payload(path)
    assert payload == h.build_hwp_table_payload(baseline), "Table values changed"
    w = read_cached_sheets(path, {s: {r} for s, r in h._REPORT_DATE_ROWS.items()})
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    spec = {
        "report": ([214, 215, 221, 222, 228, 229, 235], [212, 213, 219, 220, 226, 227, 233, 234]),
        "report_육계계란": ([67, 68, 74, 80, 81, 87], [65, 66, 72, 73, 78, 79, 85, 86]),
    }
    numeric_count = header_count = 0
    with ZipFile(path) as z:
        assert z.testzip() is None
        paths = _find_sheet_paths(z)
        styles = ET.fromstring(z.read("xl/styles.xml"))
        fonts = styles.find("s:fonts", ns)
        xfs = styles.find("s:cellXfs", ns)
        for sheet, (rows, headers) in spec.items():
            root = ET.fromstring(z.read(paths[sheet]))
            cells = {n.get("r"): n for n in root.findall(".//s:c", ns)}
            start = h._find_report_block_start(w[sheet], h._REPORT_DATE_ROWS[sheet], date.fromisoformat(payload["reportDate"]))
            def matching(row, column):
                found = []
                for cf in root.findall("s:conditionalFormatting", ns):
                    for ref in cf.get("sqref", "").split():
                        left, top, right, bottom = range_boundaries(ref)
                        if left <= column <= right and top <= row <= bottom:
                            found.extend(cf.findall("s:cfRule", ns))
                            break
                return found
            for column in (start + 5, start + 6):
                for row in rows:
                    rules = matching(row, column)
                    assert {rule.get("operator") for rule in rules} == {"greaterThan", "lessThan", "equal"}, (sheet, row, column)
                    numeric_count += 1
                for row in headers:
                    assert not matching(row, column), (sheet, row, column, "header included in conditional colors")
                    cell = cells[get_column_letter(column) + str(row)]
                    font = fonts[int(xfs[int(cell.get("s", "0"))].get("fontId", "0"))]
                    color = font.find("s:color", ns)
                    assert color is not None and color.get("rgb") == "FF000000", (sheet, row, column, ET.tostring(font))
                    header_count += 1
    print(f"Same 113 table cells; comparison rules: {numeric_count}, black headings: {header_count}")


if __name__ == "__main__":
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
