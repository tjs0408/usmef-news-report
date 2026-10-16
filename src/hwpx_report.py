"""HWPX 주간 보고서의 표와 8개 그래프를 함께 현행화한다.

한글 COM의 그림 삽입 기능은 일부 설치 환경에서 멈출 수 있어, HWPX 패키지의
표 XML과 ``BinData/image2.png``를 직접 갱신한다. 표의 위치·크기·서식은 양식의
기존 XML을 그대로 유지한다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont
from curl_cffi import requests as curl_requests
import pymupdf

from src.hwp_report import HwpReportError, build_hwp_table_payload
from src.excel_charts import EXCEL_CHARTS, read_chart_exports


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HWPX_TEMPLATE_PATH = PROJECT_ROOT / "report_template" / "weekly_overseas_market_report_table_template.hwpx"
USDA_CATTLE_BEEF_PDF_URL = "https://www.ams.usda.gov/mnreports/lsddcbs.pdf"
JZ_TOKYO_EGG_GRAPH_URL = "https://www.jz-tamago.co.jp/business/souba/graph/#tokyo"
EXCEL_CHART_BATCH_EXPORT_SCRIPT = PROJECT_ROOT / "work" / "export_excel_charts.ps1"
US_BEEF_LEGEND_REFERENCE_2026 = PROJECT_ROOT / "report_template" / "us_beef_legend_2026_reference.png"

_NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
}
_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_TABLE_INDEXES = frozenset({1, 2, 4, 5, 8, 9, 11, 12})
_RED_CHAR_STYLE_ID = "35"
_BLUE_CHAR_STYLE_ID = "36"
_BLACK_CHAR_STYLE_ID = "41"


def write_hwpx_table_report(
    excel_path: Path,
    output_path: Path,
    report_date=None,
    template_path: Path = HWPX_TEMPLATE_PATH,
    chart_output_directory: Path | None = None,
) -> dict[str, object]:
    """Excel의 최신 요약값과 연결된 6개 그래프를 HWPX 보고서에 반영한다."""
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
        report_year = date.fromisoformat(str(payload["reportDate"])).year
        # Independent source downloads overlap Excel's single COM session.
        # Package writes remain on this thread, preserving the original layout.
        japan_chart_path = staging_dir / "BinData" / "image9.png"
        if not japan_chart_path.is_file():
            raise HwpReportError("HWPX 양식에서 일본 계란 도매가격 그래프 영역을 찾지 못했습니다.")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-graph") as executor:
            us_graph = executor.submit(_download_weekly_choice_cutout_png)
            japan_graph = executor.submit(_download_jz_tokyo_egg_graph_png)
            _replace_excel_charts(staging_dir, excel_path, chart_output_directory)
            chart_path.write_bytes(us_graph.result())
            japan_chart_path.write_bytes(japan_graph.result())
        _replace_us_beef_chart_legend(staging_dir, report_year=report_year)

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
    ET.register_namespace("hc", _NS["hc"])
    _restore_us_beef_legend_frame(root)
    tree.write(section_path, encoding="UTF-8", xml_declaration=True)


def _restore_us_beef_legend_frame(root: ET.Element) -> None:
    """범례의 원래 위치를 유지하면서 양식에 남아 있던 위쪽 자르기를 해제한다."""
    for picture in root.findall(".//hp:pic", _NS):
        image = picture.find("hc:img", _NS)
        if image is None or image.get("binaryItemIDRef") != "image1":
            continue
        clip = picture.find("hp:imgClip", _NS)
        if clip is not None:
            clip.set("top", "0")
        return


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
        elif color == "black":
            # 원본 셀은 이전 주에 사용했던 빨강/파랑 서식을 보존할 수 있으므로,
            # 0.0%와 빈 비교값은 검정 전용 문자 서식으로 명시적으로 되돌린다.
            runs[0].set("charPrIDRef", _BLACK_CHAR_STYLE_ID)


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
            # 표 안에서 그림이 최대한 크게 보이도록 하되, 왼쪽 축의 통화·눈금
            # 표기가 잘리지 않도록 안전 여백을 둔다. (PDF마다 축 레이블의 폭이
            # 조금 달라질 수 있어, 그래프 테두리보다 왼쪽에서 시작한다.)
            # 왼쪽의 불필요한 흰 여백은 제외하고, 가격 눈금의 '$' 바로 앞에서
            # 시작하도록 자른다.
            graph = page_image.crop((1240, 162, 1792, 600))
            # 그래프의 선·축·눈금에는 별도 편집을 하지 않고 PDF 원본을 그대로
            # 사용한다. 한글 양식에 맞추기 위한 크기 조정만 수행한다.
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


def _replace_us_beef_chart_legend(staging_dir: Path, *, report_year: int) -> None:
    """원래의 세로형 범례 위치에 보고 연도 레이블을 반영한다."""
    target = staging_dir / "BinData" / "image1.bmp"
    if not target.is_file():
        raise HwpReportError("HWPX 양식에서 미국산 지육가격 그래프 범례를 찾지 못했습니다.")
    try:
        if report_year == 2026 and US_BEEF_LEGEND_REFERENCE_2026.is_file():
            # 사용자가 확인한 원본 세로 범례를 그대로 사용한다. 그림 객체의
            # 위치·크기·자르기 설정은 양식 원본을 건드리지 않아 처음 위치에 표시된다.
            with Image.open(US_BEEF_LEGEND_REFERENCE_2026) as reference:
                legend = reference.convert("RGB").resize((81, 51), Image.Resampling.LANCZOS)
                legend.save(target, format="BMP")
            return
        target.write_bytes(_render_us_beef_chart_legend(report_year))
    except Exception as error:
        raise HwpReportError(f"미국산 지육가격 그래프 범례를 갱신하지 못했습니다. ({error})") from error


def _render_us_beef_chart_legend(report_year: int) -> bytes:
    """다음 연도에도 기존 세로형 범례 크기를 유지해 그린다."""
    canvas = Image.new("RGB", (81, 51), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path), 7) if font_path.is_file() else ImageFont.load_default()

    def rounded_line(start_x: int, end_x: int, y: int, color: str, width: int) -> None:
        radius = width / 2
        draw.line((start_x, y, end_x, y), fill=color, width=width)
        draw.ellipse((start_x - radius, y - radius, start_x + radius, y + radius), fill=color)
        draw.ellipse((end_x - radius, y - radius, end_x + radius, y + radius), fill=color)

    rounded_line(8, 33, 8, "#ff0000", 2)
    rounded_line(8, 33, 23, "#33cccc", 2)
    for start_x in range(8, 34, 6):
        rounded_line(start_x, min(start_x + 3, 34), 39, "#000000", 1)

    draw.text((39, 1), str(report_year), fill="black", font=font)
    draw.text((39, 17), str(report_year - 1), fill="black", font=font)
    draw.text((39, 33), "5 yr Avg", fill="black", font=font)
    stream = BytesIO()
    canvas.save(stream, format="BMP")
    return stream.getvalue()


def _replace_japan_egg_chart(staging_dir: Path) -> None:
    """JA 전농타마고 도쿄 M란 그래프를 HWPX의 기존 그림 영역에 넣는다."""
    target = staging_dir / "BinData" / "image9.png"
    if not target.is_file():
        raise HwpReportError("HWPX 양식에서 일본 계란 도매가격 그래프 영역을 찾지 못했습니다.")
    target.write_bytes(_download_jz_tokyo_egg_graph_png())


def _download_jz_tokyo_egg_graph_png() -> bytes:
    """JZ 전농타마고 웹 그래프의 도쿄 M란 차트를 HWPX 크기로 렌더링한다.

    해당 페이지는 이미지 파일이 아니라 Chart.js 캔버스로 그래프를 그린다. 원본
    페이지의 ``tokyo6Chart`` 데이터·색상·축 범위를 읽어, 한글 양식의 기존
    image9 영역(950×479)에 맞는 PNG로 만든다.
    """
    try:
        response = curl_requests.get(
            JZ_TOKYO_EGG_GRAPH_URL,
            headers={"Accept": "text/html", "Referer": "https://www.jz-tamago.co.jp/business/souba/"},
            impersonate="chrome",
            timeout=30,
        )
        response.raise_for_status()
    except Exception as error:
        raise HwpReportError(f"JA 전농타마고 도쿄 계란 그래프를 가져오지 못했습니다. ({error})") from error

    try:
        chart_script = re.search(
            r'<canvas id="tokyo6Chart"></canvas>\s*<script[^>]*>(.*?)</script>',
            response.text,
            flags=re.DOTALL,
        )
        if chart_script is None:
            raise ValueError("tokyo6Chart 설정을 찾지 못했습니다.")
        datasets: list[tuple[str, list[float], str, bool]] = []
        dataset_pattern = re.compile(
            r"label:\s*'([^']+)'[\s\S]*?data:\s*\[([^\]]*)\][\s\S]*?"
            r'pointStyle:\s*"([^"]+)"[\s\S]*?pointBackgroundColor:\s*"(#[0-9A-Fa-f]{6})"',
        )
        for label, raw_values, point_style, color in dataset_pattern.findall(chart_script.group(1)):
            values = [float(value.strip()) for value in raw_values.split(",") if value.strip()]
            if values:
                datasets.append((label, values, color, point_style == "circle"))
        if not datasets:
            raise ValueError("도쿄 그래프의 월별 데이터를 읽지 못했습니다.")
        return _render_japan_egg_chart(datasets)
    except Exception as error:
        raise HwpReportError(f"JA 전농타마고 도쿄 계란 그래프를 처리하지 못했습니다. ({error})") from error


def _render_japan_egg_chart(datasets: list[tuple[str, list[float], str, bool]]) -> bytes:
    """원본 Chart.js 차트의 선·축·범례 구성을 950×479 PNG로 재현한다."""
    width, height = 950, 479
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
    font = ImageFont.truetype(str(font_path), 14) if font_path.is_file() else ImageFont.load_default()
    legend_font = ImageFont.truetype(str(font_path), 13) if font_path.is_file() else ImageFont.load_default()

    # HWPX 표 안에서 차트가 작아 보이지 않도록 원본 캔버스의 상단 여백을
    # 줄이고, 400 눈금 표기가 남을 만큼만 여유를 둔다.
    left, right, top, bottom = 37, 945, 20, 415
    minimum, maximum = 100.0, 400.0
    grid_color = "#d9d9d9"
    for tick in (100, 200, 300, 400):
        y = round(bottom - (tick - minimum) / (maximum - minimum) * (bottom - top))
        draw.line((left, y, right, y), fill=grid_color, width=1)
        label = str(tick)
        text_box = draw.textbbox((0, 0), label, font=font)
        draw.text((left - 10 - (text_box[2] - text_box[0]), y - 8), label, fill="#333333", font=font)
    for index in range(13):
        x = round(77 + index * (829 / 11)) if index < 12 else 906
        draw.line((x, top, x, bottom), fill=grid_color, width=1)
    draw.line((left, top, left, bottom), fill="#999999", width=1)

    month_labels = [f"{item}월" for item in range(1, 13)]
    x_values = [round(77 + index * (829 / 11)) for index in range(12)]
    for x, label in zip(x_values, month_labels):
        box = draw.textbbox((0, 0), label, font=font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 10), label, fill="#666666", font=font)

    # 원본 Chart.js가 선언한 순서를 유지하되, 최신(원형 표식) 선이 항상 잘
    # 보이도록 마지막에 그린다.
    for label, values, color, is_current_year in sorted(datasets, key=lambda item: item[3]):
        points = [
            (x_values[index], round(bottom - (value - minimum) / (maximum - minimum) * (bottom - top)))
            for index, value in enumerate(values[:12])
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=1)
        for x, y in points:
            if is_current_year:
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
            else:
                draw.rectangle((x - 4, y - 4, x + 4, y + 4), fill=color)

    legend_x = 536
    legend_y = 456
    for label, _, color, is_current_year in datasets:
        if is_current_year:
            draw.ellipse((legend_x, legend_y - 7, legend_x + 14, legend_y + 7), fill=color)
        else:
            draw.rectangle((legend_x, legend_y - 6, legend_x + 12, legend_y + 6), fill=color)
        draw.text((legend_x + 18, legend_y - 9), label, fill="#555555", font=legend_font)
        label_width = draw.textbbox((0, 0), label, font=legend_font)[2]
        legend_x += 18 + label_width + 12

    stream = BytesIO()
    canvas.save(stream, format="PNG")
    return stream.getvalue()


def _replace_excel_charts(staging_dir: Path, excel_path: Path, chart_output_directory: Path | None = None) -> None:
    """Excel 그래프를 한 번에 내보내 HWPX 원본 영역에 넣는다.

    Excel COM을 차트마다 새로 시작하면 시작·파일 열기 비용이 누적된다. 다섯 개
    차트를 하나의 읽기 전용 Excel 세션에서 PNG로 내보낸 뒤, Python에서 HWPX용
    BMP 크기만 각각 맞춘다.
    """
    charts = EXCEL_CHARTS

    for label, filename, _, _, _ in charts:
        target = staging_dir / "BinData" / filename
        if not target.is_file():
            raise HwpReportError(f"HWPX 양식에서 {label} 그래프 영역을 찾지 못했습니다.")

    # Only exports from this exact saved workbook (size + nanosecond mtime +
    # chart mapping) can be reused. Otherwise keep the existing COM fallback.
    png_paths = read_chart_exports(chart_output_directory, excel_path)
    if png_paths is None:
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
