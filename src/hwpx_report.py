"""HWPX 주간 보고서의 표와 미국산 지육가격 그래프를 함께 현행화한다.

한글 COM의 그림 삽입 기능은 일부 설치 환경에서 멈출 수 있어, HWPX 패키지의
표 XML과 ``BinData/image2.png``를 직접 갱신한다. 표의 위치·크기·서식은 양식의
기존 XML을 그대로 유지한다.
"""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

from PIL import Image
import pymupdf

from src.hwp_report import HwpReportError, build_hwp_table_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HWPX_TEMPLATE_PATH = PROJECT_ROOT / "report_template" / "weekly_overseas_market_report_table_template.hwpx"
USDA_CATTLE_BEEF_PDF_URL = "https://www.ams.usda.gov/mnreports/lsddcbs.pdf"
EXCEL_CHART_BATCH_EXPORT_SCRIPT = PROJECT_ROOT / "work" / "export_excel_charts.ps1"

_NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_TABLE_INDEXES = frozenset({1, 2, 4, 5, 8, 9, 11, 12})
_RED_CHAR_STYLE_ID = "35"
_BLUE_CHAR_STYLE_ID = "36"


def write_hwpx_table_report(
    excel_path: Path,
    output_path: Path,
    report_date=None,
    template_path: Path = HWPX_TEMPLATE_PATH,
) -> dict[str, object]:
    """Excel의 최신 요약값과 USDA 컷아웃 그래프를 HWPX 보고서에 반영한다."""
    if not template_path.is_file():
        raise HwpReportError(f"HWPX 한글 보고서 양식을 찾지 못했습니다. ({template_path.name})")

    payload = build_hwp_table_payload(excel_path, report_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = output_path.parent / f".{output_path.stem}_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    try:
        with zipfile.ZipFile(template_path, "r") as package:
            package.extractall(staging_dir)

        section_path = staging_dir / "Contents" / "section0.xml"
        if not section_path.is_file():
            raise HwpReportError("HWPX 양식에서 본문 XML을 찾지 못했습니다.")
        _update_section_xml(section_path, payload)

        chart_path = staging_dir / "BinData" / "image2.png"
        if not chart_path.is_file():
            raise HwpReportError("HWPX 양식에서 미국산 지육가격 그래프 영역을 찾지 못했습니다.")
        chart_path.write_bytes(_download_weekly_choice_cutout_png())

        _replace_excel_charts(staging_dir, excel_path)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for source in staging_dir.rglob("*"):
                if source.is_file():
                    package.write(source, source.relative_to(staging_dir).as_posix())
    except HwpReportError:
        raise
    except Exception as error:  # pragma: no cover - network / HWPX errors vary by environment
        raise HwpReportError(f"HWPX 한글 보고서를 저장하지 못했습니다. ({error})") from error
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise HwpReportError("HWPX 한글 보고서 결과 파일을 만들지 못했습니다.")
    return payload


def _update_section_xml(section_path: Path, payload: dict[str, object]) -> None:
    tree = ET.parse(section_path)
    root = tree.getroot()
    _replace_report_title_dates(root, str(payload["titleDateLabel"]))
    tables = root.findall(".//hp:tbl", _NS)

    for update in payload["tables"]:
        table_index = int(update["tableIndex"])
        if table_index not in _TABLE_INDEXES or table_index >= len(tables):
            raise HwpReportError(f"HWPX 양식의 표 위치가 달라졌습니다. (tableIndex={table_index})")
        _update_table_cells(tables[table_index], update["cells"])

    ET.register_namespace("hp", _NS["hp"])
    tree.write(section_path, encoding="UTF-8", xml_declaration=True)


def _replace_report_title_dates(root: ET.Element, title_date_label: str) -> None:
    # 상단 제목은 '(9.10.)' 같은 완결된 날짜 표기만 사용하므로 다른 본문 수치에는
    # 영향을 주지 않는다.
    for text in root.findall(".//hp:t", _NS):
        value = text.text or ""
        if value.startswith("(") and value.endswith(".)") and value.count(".") == 2:
            middle = value[1:-2]
            if all(part.isdigit() for part in middle.split(".")):
                text.text = title_date_label


def _update_table_cells(table: ET.Element, cells: list[dict[str, object]]) -> None:
    by_address: dict[tuple[int, int], ET.Element] = {}
    for cell in table.findall(".//hp:tc", _NS):
        address = cell.find("hp:cellAddr", _NS)
        if address is not None:
            by_address[(int(address.get("rowAddr", "-1")), int(address.get("colAddr", "-1")))] = cell

    for update in cells:
        address = (int(update["row"]), int(update["column"]))
        cell = by_address.get(address)
        if cell is None:
            raise HwpReportError(f"HWPX 표의 대상 셀을 찾지 못했습니다. ({address[0]},{address[1]})")
        runs = cell.findall(".//hp:run", _NS)
        if not runs:
            raise HwpReportError(f"HWPX 표의 대상 셀 서식을 찾지 못했습니다. ({address[0]},{address[1]})")
        text_nodes = cell.findall(".//hp:t", _NS)
        if text_nodes:
            text_nodes[0].text = str(update.get("value", ""))
            for extra in text_nodes[1:]:
                extra.text = ""
        else:
            text_node = ET.Element(f"{_HP}t")
            text_node.text = str(update.get("value", ""))
            runs[0].insert(0, text_node)

        color = str(update.get("comparisonColor") or "")
        if color == "red":
            runs[0].set("charPrIDRef", _RED_CHAR_STYLE_ID)
        elif color == "blue":
            runs[0].set("charPrIDRef", _BLUE_CHAR_STYLE_ID)


def _download_weekly_choice_cutout_png() -> bytes:
    request = urllib.request.Request(
        USDA_CATTLE_BEEF_PDF_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WeeklyMarketReport/1.0)", "Accept": "application/pdf,*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            pdf_bytes = response.read()
    except Exception as error:
        raise HwpReportError(f"USDA 미국산 지육가격 그래프를 가져오지 못했습니다. ({error})") from error

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page = document[0]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(220 / 72, 220 / 72), alpha=False)
        # 현행 USDA 보고서 1쪽의 Weekly Choice Cutout 그래프: 제목·범례는 제외하고
        # 축·월 표기·우측 테두리를 모두 포함한다. HWPX 원본 image2.png와 같은
        # 332×254로 저장해야 한글이 전체를 표시한다.
        with Image.open(BytesIO(pixmap.tobytes("png"))) as page_image:
            # 원본 그래프의 흰 왼쪽 여백은 제외해 실제 그래프가 표 영역을 충분히
            # 채우도록 한다. y축의 $ 표기와 오른쪽 테두리는 그대로 보존한다.
            graph = page_image.crop((1239, 162, 1792, 600))
            fitted = graph.resize((332, 254), Image.Resampling.LANCZOS)
            stream = BytesIO()
            fitted.save(stream, format="PNG")
            return stream.getvalue()
    except Exception as error:
        raise HwpReportError(f"USDA 미국산 지육가격 그래프를 자르지 못했습니다. ({error})") from error
    finally:
        try:
            document.close()
        except UnboundLocalError:
            pass


def _replace_excel_charts(staging_dir: Path, excel_path: Path) -> None:
    """Excel 그래프를 한 번에 내보내 HWPX 원본 영역에 넣는다.

    Excel COM을 차트마다 새로 시작하면 시작·파일 열기 비용이 누적된다. 다섯 개
    차트를 하나의 읽기 전용 Excel 세션에서 PNG로 내보낸 뒤, Python에서 HWPX용
    BMP 크기만 각각 맞춘다.
    """
    charts = (
        ("호주산 어린소가격", "image3.bmp", 4, 166, (736, 343)),  # 소-호주 FJ
        ("미국산 지육가격", "image4.bmp", 5, 169, (754, 330)),  # 돼지-미국 FM
        ("독일산 지육가격", "image5.bmp", 6, 329, (833, 341)),  # 돼지-EU(독일) LQ
        ("미국산 신선 WOG(통닭) 가격", "image6.bmp", 8, 8, (595, 292)),  # 미국 육계 그래프(WOG) H
        ("브라질 육계 가격", "image7.bmp", 10, 12, (1110, 411)),  # 브라질그래프 L
    )

    for label, filename, _, _, _ in charts:
        target = staging_dir / "BinData" / filename
        if not target.is_file():
            raise HwpReportError(f"HWPX 양식에서 {label} 그래프 영역을 찾지 못했습니다.")

    png_paths = _export_excel_charts_png(excel_path, charts)
    for chart_index, (label, filename, _, _, image_size) in enumerate(charts, start=1):
        target = staging_dir / "BinData" / filename
        target.write_bytes(_convert_chart_to_bmp(png_paths[chart_index], image_size, label))


def _export_excel_charts_png(
    excel_path: Path,
    charts: tuple[tuple[str, str, int, int, tuple[int, int]], ...],
) -> dict[int, bytes]:
    """읽기 전용 Excel 세션 하나에서 지정 차트를 모두 PNG로 내보낸다."""
    if not EXCEL_CHART_BATCH_EXPORT_SCRIPT.is_file():
        raise HwpReportError("Excel 그래프 일괄 내보내기 도구를 찾지 못했습니다.")

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise HwpReportError("Excel 그래프를 내보낼 PowerShell을 찾지 못했습니다.")

    with tempfile.TemporaryDirectory(prefix="hwpx_excel_charts_") as temporary_directory:
        # Windows PowerShell의 인수 코드페이지가 한글 파일명을 깨뜨릴 수 있다.
        # 읽기 전용 사본을 영문 임시 경로에 두고, 원본 업로드 파일은 건드리지 않는다.
        source_copy = Path(temporary_directory) / "source_workbook.xlsx"
        export_directory = Path(temporary_directory) / "charts"
        chart_specs_path = Path(temporary_directory) / "chart_specs.json"
        shutil.copy2(excel_path, source_copy)
        chart_specs_path.write_text(
            json.dumps(
                [
                    {
                        "outputName": f"chart_{index}.png",
                        "sheetIndex": sheet_index,
                        "anchorColumn": anchor_column,
                    }
                    for index, (_, _, sheet_index, anchor_column, _) in enumerate(charts, start=1)
                ]
            ),
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(EXCEL_CHART_BATCH_EXPORT_SCRIPT),
                    "-WorkbookPath",
                    str(source_copy),
                    "-OutputDirectory",
                    str(export_directory),
                    "-ChartSpecsPath",
                    str(chart_specs_path),
                ],
                capture_output=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise HwpReportError("Excel 그래프를 일괄 내보내는 시간이 초과되었습니다.") from error

        if result.returncode != 0:
            raw_details = result.stderr or result.stdout
            details = raw_details.decode("utf-8", errors="replace").strip() if raw_details else "알 수 없는 오류"
            raise HwpReportError(f"Excel 그래프를 일괄 내보내지 못했습니다. ({details})")

        exported: dict[int, bytes] = {}
        for index, (label, _, _, _, _) in enumerate(charts, start=1):
            png_path = export_directory / f"chart_{index}.png"
            if not png_path.is_file() or png_path.stat().st_size == 0:
                raise HwpReportError(f"{label} 그래프 PNG 파일을 만들지 못했습니다.")
            # TemporaryDirectory가 지워지기 전에 이미지 바이트를 보관한다.
            exported[index] = png_path.read_bytes()
        return exported


def _convert_chart_to_bmp(png_bytes: bytes, image_size: tuple[int, int], label: str) -> bytes:
    """내보낸 Excel 차트를 HWPX의 기존 그림 크기·외곽선 규격으로 변환한다."""
    try:
        # HWPX의 기존 그림 크기를 그대로 지켜야 이미지가 잘리거나 작아지지
        # 않는다. 각 차트 영역의 화면 비율에 맞춰 변환한다.
        with Image.open(BytesIO(png_bytes)) as chart:
            source = chart.convert("RGB")
            if source.width <= 4 or source.height <= 4:
                raise ValueError("차트 이미지가 너무 작습니다.")
            # Excel 차트 내보내기 결과의 가장 바깥 1px 회색/검정 테두리는
            # 한글 보고서의 표 선과 겹쳐 보인다. 데이터·축에는 닿지 않도록
            # 바깥쪽 2px만 제거한 뒤 기존 그림 크기로 맞춘다.
            trimmed = source.crop((2, 2, source.width - 2, source.height - 2))
            fitted = trimmed.resize(image_size, Image.Resampling.LANCZOS)
            stream = BytesIO()
            fitted.save(stream, format="BMP")
            return stream.getvalue()
    except Exception as error:
        raise HwpReportError(f"{label} 그래프 이미지를 변환하지 못했습니다. ({error})") from error
