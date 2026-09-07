"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from flask import Flask, redirect, render_template, send_file, url_for

from src.crawler import fetch_latest_market_data
from src.excel_writer import write_market_data_to_excel


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

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
    """최신 소고기 지표를 수집하고 생성한 Excel 파일을 내려줍니다."""
    try:
        market_data = fetch_latest_market_data()
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"usmef_weekly_market_report_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
        write_market_data_to_excel(market_data, report_path)
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
