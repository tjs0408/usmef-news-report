"""USMEF 뉴스 Excel 보고서를 생성하는 로컬 웹 애플리케이션입니다."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from flask import Flask, render_template, send_file

from src.crawler import fetch_latest_news
from src.excel_writer import write_news_to_excel


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

app = Flask(__name__)


@app.get("/")
def index() -> str:
    """보고서 생성 화면을 보여줍니다."""
    return render_template("index.html")


@app.post("/generate-report")
def generate_report():
    """최신 뉴스를 수집하고 생성한 Excel 파일을 내려줍니다."""
    news_items = fetch_latest_news()
    created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"usmef_newsline_{created_at}.xlsx"
    report_path = OUTPUT_DIR / report_filename
    write_news_to_excel(news_items, report_path)

    return send_file(
        report_path,
        as_attachment=True,
        download_name=report_filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
