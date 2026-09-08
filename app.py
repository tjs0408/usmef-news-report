"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path

from flask import Flask, redirect, render_template, send_file, url_for

from src.crawler import fetch_market_data_for_report_dates
from src.template_report import find_pending_report_dates, write_market_data_to_template


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATE_PATH = PROJECT_ROOT / "report_template" / "해외시장_수급_및_가격_동향_양식.xlsx"

app = Flask(__name__)


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
    """양식의 비어 있는 주차 행에 USMEF 소고기 지표를 채워 내려줍니다."""
    try:
        if not TEMPLATE_PATH.exists():
            raise RuntimeError("보고서 엑셀 양식을 찾지 못했습니다.")
        pending_rows = find_pending_report_dates(TEMPLATE_PATH, date.today())
        if not pending_rows:
            raise RuntimeError("현재 양식에서 현행화할 주차가 없습니다.")
        report_dates = {date.fromisoformat(str(row["reportDate"])) for row in pending_rows}
        market_data = fetch_market_data_for_report_dates(report_dates)
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
        write_market_data_to_template(TEMPLATE_PATH, report_path, pending_rows, market_data)
    except RuntimeError as error:
        app.logger.exception("USMEF 뉴스라인 보고서 생성 실패")
        return f"보고서 생성에 실패했습니다: {error}", 502

    return send_file(
        report_path,
        as_attachment=True,
        download_name=report_filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
