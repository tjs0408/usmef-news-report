"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import tempfile
from threading import Lock, Thread
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from src.crawler import fetch_market_data_for_report_dates
from src.template_report import find_pending_report_dates, write_market_data_to_template


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
REPORT_JOBS: dict[str, dict[str, object]] = {}
REPORT_JOBS_LOCK = Lock()


@app.get("/")
def index() -> str:
    """보고서 생성 화면을 보여줍니다."""
    return render_template("index.html")


@app.get("/generate-report")
def generate_report_page():
    """주소창 새로고침으로 POST 주소에 접근한 경우 생성 화면으로 돌려보냅니다."""
    return redirect(url_for("index"))


@app.post("/start-report")
def start_report():
    """업로드 파일을 기준으로 비동기 보고서 생성 작업을 시작합니다."""
    uploaded_template = request.files.get("template_file")
    if uploaded_template is None or not uploaded_template.filename:
        return jsonify(error="기준으로 사용할 Excel 파일을 업로드해 주세요."), 400
    if Path(uploaded_template.filename).suffix.lower() != ".xlsx":
        return jsonify(error=".xlsx 형식의 Excel 파일만 업로드할 수 있습니다."), 400

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(suffix=".xlsx", dir=OUTPUT_DIR)
    os.close(descriptor)
    temporary_template_path = Path(temporary_name)
    uploaded_template.save(temporary_template_path)

    job_id = uuid4().hex
    _update_job(job_id, status="running", progress=5, message="업로드한 엑셀 양식을 확인하고 있습니다.")
    Thread(target=_run_report_job, args=(job_id, temporary_template_path), daemon=True).start()
    return jsonify(jobId=job_id)


@app.get("/report-status/<job_id>")
def report_status(job_id: str):
    """진행 중인 보고서 생성 작업의 상태를 반환합니다."""
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.get(job_id)
        if job is None:
            return jsonify(error="보고서 생성 작업을 찾지 못했습니다."), 404
        return jsonify(job)


@app.get("/download-report/<job_id>")
def download_report(job_id: str):
    """완료된 보고서 파일을 내려줍니다."""
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.get(job_id)
        if job is None or job.get("status") != "completed":
            return "아직 보고서 생성이 완료되지 않았습니다.", 409
        report_path = Path(str(job["reportPath"]))
        report_filename = str(job["reportFilename"])

    return send_file(
        report_path,
        as_attachment=True,
        download_name=report_filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _run_report_job(job_id: str, template_path: Path) -> None:
    """뉴스 수집과 Excel 생성을 실행하고 단계별 진행률을 기록합니다."""
    try:
        pending_rows = find_pending_report_dates(template_path, date.today())
        if not pending_rows:
            raise RuntimeError("현재 양식에서 현행화할 주차가 없습니다.")
        report_dates = {date.fromisoformat(str(row["reportDate"])) for row in pending_rows}
        _update_job(job_id, progress=15, message=f"현행화할 뉴스 {len(report_dates)}건을 찾았습니다.")

        def update_ocr_progress(index: int, total: int, report_date: date, stage: str) -> None:
            completed_count = index - 1 if stage == "started" else index
            progress = 20 + round(completed_count / total * 50)
            message = (
                f"뉴스라인 {index}/{total}건을 분석하고 있습니다. ({report_date:%Y-%m-%d})"
                if stage == "started"
                else f"뉴스라인 {index}/{total}건 분석을 완료했습니다. ({report_date:%Y-%m-%d})"
            )
            _update_job(
                job_id,
                progress=progress,
                message=message,
            )

        market_data = fetch_market_data_for_report_dates(report_dates, update_ocr_progress)
        _update_job(job_id, progress=75, message="수집한 값을 엑셀 양식에 입력하고 있습니다.")
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
        write_market_data_to_template(template_path, report_path, pending_rows, market_data)
        _update_job(
            job_id,
            status="completed",
            progress=100,
            message="보고서 생성이 완료되었습니다. 다운로드를 시작합니다.",
            reportPath=str(report_path),
            reportFilename=report_filename,
        )
    except RuntimeError as error:
        app.logger.exception("USMEF 뉴스라인 보고서 생성 실패")
        _update_job(job_id, status="failed", progress=0, message=f"보고서 생성에 실패했습니다: {error}")
    finally:
        template_path.unlink(missing_ok=True)


def _update_job(job_id: str, **changes: object) -> None:
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.setdefault(job_id, {})
        job.update(changes)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
