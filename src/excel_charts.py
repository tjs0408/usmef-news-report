"""Shared chart mapping and verified per-workbook export cache."""
import json
from pathlib import Path

EXCEL_CHARTS = (
    ("호주산 어린소가격", "image3.bmp", 4, 166, (736, 343)),
    ("미국산 지육가격", "image4.bmp", 5, 169, (754, 330)),
    ("독일산 지육가격", "image5.bmp", 6, 329, (833, 341)),
    ("미국산 신선 WOG(통닭) 가격", "image6.bmp", 8, 8, (595, 292)),
    ("브라질 육계 가격", "image7.bmp", 10, 12, (1110, 411)),
    ("미국 계란 소매가격(Large, A)", "image8.bmp", 11, 37, (796, 373)),
)


def chart_specs(charts=EXCEL_CHARTS):
    return [{"outputName": f"chart_{i}.png", "sheetIndex": sheet, "anchorColumn": anchor}
            for i, (_, _, sheet, anchor, _) in enumerate(charts, 1)]


def _signature(workbook: Path):
    stat = workbook.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "charts": chart_specs()}


def record_chart_exports(directory: Path, workbook: Path):
    if all((directory / spec["outputName"]).is_file() and (directory / spec["outputName"]).stat().st_size > 0
           for spec in chart_specs()):
        (directory / "manifest.json").write_text(json.dumps(_signature(workbook)), encoding="utf-8")


def read_chart_exports(directory: Path | None, workbook: Path):
    if directory is None:
        return None
    try:
        if json.loads((directory / "manifest.json").read_text(encoding="utf-8")) != _signature(workbook):
            return None
        data = {i: (directory / spec["outputName"]).read_bytes()
                for i, spec in enumerate(chart_specs(), 1)}
        return data if all(data.values()) else None
    except (OSError, ValueError):
        return None
