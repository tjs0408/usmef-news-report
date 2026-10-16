"""Read selected cached Excel values without loading drawings or changing files."""
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .template_report import SPREADSHEET_NAMESPACE, _find_sheet_paths

_S = f"{{{SPREADSHEET_NAMESPACE}}}"


class CachedWorksheet:
    def __init__(self, title: str, values: dict[tuple[int, int], object]):
        self.title = title
        self.values = values
        self.max_column = max((column for _, column in values), default=0)

    def cell(self, row: int, column: int):
        return SimpleNamespace(value=self.values.get((row, column)))


def read_cached_sheets(path: Path, rows_by_sheet: dict[str, set[int]]) -> dict[str, CachedWorksheet]:
    """Only Excel-saved formula results are read; never evaluate formulas here.

    Supports numeric/boolean/error, shared and inline strings and formula string
    caches. Report rows use strings for dates and raw numbers for metrics.
    """
    with ZipFile(path) as archive:
        sheet_paths = _find_sheet_paths(archive)
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            # Rich text contains formatting elements, not display text.
            strings = ["".join(t.text or "" for t in node.iter(f"{_S}t")) for node in root.findall(f"{_S}si")]
        sheets = {}
        for name, selected_rows in rows_by_sheet.items():
            values = {}
            with archive.open(sheet_paths[name]) as source:
                for _, row in ET.iterparse(source, events=("end",)):
                    if row.tag != f"{_S}row":
                        continue
                    row_number = int(row.get("r", "0"))
                    if row_number in selected_rows:
                        for cell in row.findall(f"{_S}c"):
                            reference = cell.get("r", "")
                            column = 0
                            for letter in reference:
                                if not letter.isalpha():
                                    break
                                column = column * 26 + ord(letter) - ord("A") + 1
                            kind = cell.get("t", "n")
                            value = cell.findtext(f"{_S}v")
                            if kind == "inlineStr":
                                value = "".join(t.text or "" for t in cell.iter(f"{_S}t"))
                            elif value is None:
                                continue
                            elif kind == "s":
                                value = strings[int(value)]
                            elif kind == "b":
                                value = value == "1"
                            elif kind == "n":
                                value = float(value)
                                if value.is_integer():
                                    value = int(value)
                            values[(row_number, column)] = value
                    row.clear()
            sheets[name] = CachedWorksheet(name, values)
        return sheets
