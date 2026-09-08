"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import tempfile

from flask import Flask, redirect, render_template, request, send_file, url_for

from src.crawler import fetch_market_data_for_report_dates
from src.template_report import find_pending_report_dates, write_market_data_to_template


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024


@app.get("/")
def index() -> str:
    """보고서 생성 화면을 보여줍니다."""
    return render_template("index.html")


@app.get("/generate-report")
def generate_report_page():
    """주소창 새로고침으로 POST 주소에 접근한 경우 생성 화면으로 돌려보냅니다."""
    return redirect(url_for("index"))


@app.post("/generate-report")
def generate_report():
    """업로드한 양식의 비어 있는 주차 행에 USMEF 시장 지표를 채워 내려줍니다."""
    uploaded_template = request.files.get("template_file")
    temporary_template_path: Path | None = None
    try:
        if uploaded_template is None or not uploaded_template.filename:
            raise RuntimeError("기준으로 사용할 Excel 파일을 업로드해 주세요.")
        if Path(uploaded_template.filename).suffix.lower() != ".xlsx":
            raise RuntimeError(".xlsx 형식의 Excel 파일만 업로드할 수 있습니다.")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(suffix=".xlsx", dir=OUTPUT_DIR)
        os.close(descriptor)
        temporary_template_path = Path(temporary_name)
        uploaded_template.save(temporary_template_path)

        pending_rows = find_pending_report_dates(temporary_template_path, date.today())
        if not pending_rows:
            raise RuntimeError("현재 양식에서 현행화할 주차가 없습니다.")
        report_dates = {date.fromisoformat(str(row["reportDate"])) for row in pending_rows}
        market_data = fetch_market_data_for_report_dates(report_dates)
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
        write_market_data_to_template(temporary_template_path, report_path, pending_rows, market_data)
    except RuntimeError as error:
        app.logger.exception("USMEF 뉴스라인 보고서 생성 실패")
        return f"보고서 생성에 실패했습니다: {error}", 502
    finally:
        if temporary_template_path is not None:
            temporary_template_path.unlink(missing_ok=True)

    return send_file(
        report_path,
        as_attachment=True,
        download_name=report_filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
