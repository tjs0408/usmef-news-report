"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge


# 로컬 비공개 설정(.env)을 먼저 읽어 외부 API 키가 소스나 Git에 남지 않게 한다.
load_dotenv(Path(__file__).resolve().parent / ".env")

from src.crawler import (
    fetch_ahdb_germany_pig_prices,
    fetch_aud_krw_exchange_rates,
    fetch_brl_krw_exchange_rates,
    fetch_cepea_brazil_chicken_prices,
    fetch_eur_krw_exchange_rates,
    fetch_fred_us_egg_consumer_prices,
    fetch_jpy_krw_exchange_rates,
    fetch_jz_tokyo_egg_prices,
    fetch_market_data_for_report_dates,
    fetch_mla_australia_cattle_data,
    fetch_usda_us_chicken_data,
    fetch_usda_us_egg_data,
    fetch_usd_krw_exchange_rates,
)
from src.template_report import (
    find_pending_rows,
    write_market_data_to_template,
)
from src.hwp_report import HwpReportError
from src.hwpx_report import write_hwpx_table_report
from src.overseas_article_digest import (
    ArticleDigestError,
    collect_weekly_article_summaries,
    collect_weekly_beef_report_draft,
)
from src.livestock_article_draft import SECTION_GROUPS, SECTION_SPECS, collect_weekly_livestock_report_draft
from src.article_cancellation import ArticleDraftCancelled
from src.article_hwpx import ArticleHwpxError, apply_article_draft_to_hwpx
from src.report_brief_style import STYLE_VERSION, SUMMARY_LIMITS, SUMMARY_MIN_LENGTH


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
# 닭-브라질 및 브라질그래프 수집을 함께 제어한다.
# 접속 제한 시 False로 보류할 수 있으며, 개별 수집 실패는 아래에서 처리한다.
CEPEA_COLLECTION_ENABLED = True

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
REPORT_JOBS: dict[str, dict[str, object]] = {}
REPORT_JOBS_LOCK = Lock()
ARTICLE_JOBS: dict[str, dict[str, object]] = {}
ARTICLE_JOBS_LOCK = Lock()
ARTICLE_CANCELLED_REQUESTS: dict[str, float] = {}


def _article_request_id(payload) -> str:
    value = str(payload.get("requestId", ""))
    if value and (len(value) != 32 or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError("Invalid article request ID")
    return value


def _prune_article_cancellations():
    # A reload can send cancel BEFORE the original start request arrives.
    # Retain short-lived tombstones so that late starts cannot revive the job.
    cutoff = monotonic() - 300
    for identity in list(ARTICLE_CANCELLED_REQUESTS):
        if ARTICLE_CANCELLED_REQUESTS[identity] < cutoff or len(ARTICLE_CANCELLED_REQUESTS) > 256:
            del ARTICLE_CANCELLED_REQUESTS[identity]


@app.get("/")
def index() -> str:
    """보고서 생성 화면을 보여줍니다."""
    return render_template(
        "index.html",
        cepea_enabled=CEPEA_COLLECTION_ENABLED,
        active_sheet_count=10 if CEPEA_COLLECTION_ENABLED else 8,
        default_report_date=date.today().isoformat(),
        article_groups=SECTION_GROUPS,
        article_style_version=STYLE_VERSION,
    )


@app.get("/local-server-state")
def local_server_state():
    """Expose only local launcher readiness and busy flags, never job details."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return "", 404
    with ARTICLE_JOBS_LOCK:
        article_busy = any(job.get("status") in ("running", "cancelling")
                           for job in ARTICLE_JOBS.values())
    with REPORT_JOBS_LOCK:
        report_busy = any(job.get("status") == "running" for job in REPORT_JOBS.values())
    response = jsonify(pid=os.getpid(), styleVersion=STYLE_VERSION,
                       articleBusy=article_busy, reportBusy=report_busy,
                       busy=article_busy or report_busy)
    response.headers["Cache-Control"] = "no-store"
    return response


def _validate_hwpx_article_draft(draft: object) -> dict:
    """Validate completed briefs and explicitly blank terminal missing items."""
    if not isinstance(draft, dict):
        raise ValueError("기사 초안 정보를 확인하지 못했습니다. 초안을 다시 만들어 주세요.")
    try:
        report_date = date.fromisoformat(draft.get("reportDate", ""))
        if report_date.isoformat() != draft["reportDate"]:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("기사 초안의 보고 기준일을 확인해 주세요.") from None
    start = report_date - timedelta(days=(report_date.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    for field, expected in (("weekStart", start), ("weekEnd", end)):
        if field in draft and draft[field] != expected.isoformat():
            raise ValueError("기사 초안의 검색 기간이 선택한 주차와 다릅니다. 다시 실행해 주세요.")
    sections = draft.get("sections")
    keys = {spec.key for spec in SECTION_SPECS}
    if not isinstance(sections, dict) or not set(sections).issubset(keys):
        raise ValueError("기사 초안의 국가·축종 항목을 확인해 주세요.")
    ready = 0
    normalized = {}
    terminal_statuses = {"completed", "no_article", "source_error", "summary_error", "model_unavailable", "missing"}
    for spec in SECTION_SPECS:
        if spec.key not in sections:
            normalized[spec.key] = {"status": "missing", "summary": "", "article": None}
            continue
        section = sections[spec.key]
        if (not isinstance(section, dict) or not isinstance(section.get("status"), str)
                or section.get("status") not in terminal_statuses):
            raise ValueError(f"{spec.label} 기사 작업이 끝난 뒤 반영해 주세요.")
        summary = section.get("summary")
        if section.get("status") != "completed" or summary is None or summary == "":
            # Never insert a rejected draft, error message, or stale citation.
            normalized[spec.key] = {"status": "missing", "summary": "", "article": None}
            continue
        if (not isinstance(summary, str) or summary != summary.strip()
                or not SUMMARY_MIN_LENGTH <= len(summary) <= SUMMARY_LIMITS[spec.key]
                or re.search(r"[\x00-\x1f\x7f]|다[.!]?$", summary)
                or re.match(r"[-∙]?\s*\(현지동향\)", summary)):
            raise ValueError(f"{spec.label} 요약의 길이·개조식 문체를 확인해 주세요.")
        article = section.get("article")
        if not isinstance(article, dict):
            raise ValueError(f"{spec.label} 원문 정보를 확인해 주세요.")
        for field, limit in (("title", 300), ("publisher", 120), ("url", 2048)):
            value = article.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > limit
                    or re.search(r"[\x00-\x1f\x7f]", value)):
                raise ValueError(f"{spec.label} 원문 제목·매체·링크를 확인해 주세요.")
        try:
            url = urlsplit(article["url"])
            if url.scheme not in ("https", "http") or not url.hostname:
                raise ValueError
            published = date.fromisoformat(article.get("publishedDate", ""))
            if published.isoformat() != article["publishedDate"] or not start <= published <= end:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"{spec.label} 원문 링크·발행일이 해당 주차 조건에 맞지 않습니다.") from None
        normalized[spec.key] = section
        ready += 1
    if ready == 0:
        raise ValueError("반영 가능한 완료 초안이 1개 이상 있어야 합니다. 기사 초안을 먼저 작성해 주세요.")
    return draft if normalized == sections else {**draft, "sections": normalized}


@app.post("/apply-article-draft")
def apply_article_draft():
    """Apply completed briefs to a copy; blank any unfinished article slots."""
    try:
        uploaded = request.files.get("report_file")
        if uploaded is None or not uploaded.filename:
            return jsonify(error="가격 데이터가 반영된 한글 HWPX 파일을 선택해 주세요."), 400
        if Path(uploaded.filename).suffix.lower() != ".hwpx":
            return jsonify(error=".hwpx 파일만 반영할 수 있습니다. .hwp 파일은 한글에서 HWPX로 저장해 주세요."), 400
        raw_draft = request.form.get("draft", "")
        if len(raw_draft) > 2 * 1024 * 1024:
            return jsonify(error="기사 초안 정보가 너무 큽니다. 다시 실행해 주세요."), 400
        try:
            draft = _validate_hwpx_article_draft(json.loads(raw_draft))
        except (json.JSONDecodeError, ValueError) as error:
            message = str(error) if not isinstance(error, json.JSONDecodeError) else "기사 초안 정보를 확인하지 못했습니다. 다시 실행해 주세요."
            return jsonify(error=message), 400
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"주간_해외_수급_및_가격_동향_기사반영_{draft['reportDate'].replace('-', '')}_{uuid4().hex[:12]}.hwpx"
        output_path = OUTPUT_DIR / filename
        with tempfile.TemporaryDirectory(prefix="article-hwpx-") as staging:
            input_path = Path(staging) / "price_report.hwpx"
            uploaded.save(input_path)
            if input_path.stat().st_size == 0:
                return jsonify(error="빈 파일은 반영할 수 없습니다. 한글파일을 다시 선택해 주세요."), 400
            apply_article_draft_to_hwpx(input_path, output_path, draft)
        response = send_file(output_path, as_attachment=True, download_name=filename,
                             mimetype="application/vnd.hancom.hwpx", conditional=False)
        response.headers["Cache-Control"] = "no-store"
        applied_count = sum(section.get("status") == "completed" for section in draft["sections"].values())
        response.headers["X-Article-Applied-Count"] = str(applied_count)
        response.headers["X-Article-Blank-Count"] = str(len(SECTION_SPECS) - applied_count)
        return response
    except RequestEntityTooLarge:
        return jsonify(error="파일과 기사 정보를 합해 20MB 이하로 업로드해 주세요."), 413
    except ArticleHwpxError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        app.logger.exception("기사 초안 HWPX 반영 실패")
        return jsonify(error="한글파일에 기사 초안을 반영하지 못했습니다. 파일과 초안을 확인해 주세요."), 500


@app.get("/generate-report")
def generate_report_page():
    """주소창 새로고침으로 POST 주소에 접근한 경우 생성 화면으로 돌려보냅니다."""
    return redirect(url_for("index"))


@app.post("/article-summary")
def article_summary():
    """선택한 주차의 해외 축산시장 국내기사 후보와 로컬 AI 요약을 반환합니다."""
    payload = request.get_json(silent=True) or {}
    raw_report_date = str(payload.get("reportDate", ""))
    try:
        report_date = date.fromisoformat(raw_report_date)
    except ValueError:
        return jsonify(error="보고 기준일을 YYYY-MM-DD 형식으로 선택해 주세요."), 400
    try:
        return jsonify(collect_weekly_article_summaries(report_date))
    except ArticleDigestError as error:
        app.logger.warning("해외 동향 기사 요약 실패: %s", error)
        return jsonify(error=f"해외 동향 기사를 확인하지 못했습니다: {error}"), 502


@app.post("/beef-report-draft")
def beef_report_draft():
    """첫 페이지 쇠고기 수급·가격 동향 형식의 기사 초안을 반환합니다."""
    payload = request.get_json(silent=True) or {}
    raw_report_date = str(payload.get("reportDate", ""))
    try:
        report_date = date.fromisoformat(raw_report_date)
    except ValueError:
        return jsonify(error="보고 기준일을 YYYY-MM-DD 형식으로 선택해 주세요."), 400
    try:
        return jsonify(collect_weekly_beef_report_draft(report_date))
    except ArticleDigestError as error:
        app.logger.warning("쇠고기 주간 기사 초안 실패: %s", error)
        return jsonify(error=f"쇠고기 주간 기사를 확인하지 못했습니다: {error}"), 502


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
    _update_job(
        job_id,
        status="running",
        stage=2,
        progress=0,
        message="원본 수집 준비 중",
        # monotonic 시간은 이 프로세스 안에서만 쓰며, PC 시계 변경의 영향을 받지
        # 않는다. 화면에는 이 값을 초 단위 실측 시간으로만 전달한다.
        startedAt=monotonic(),
    )
    Thread(target=_run_report_job, args=(job_id, temporary_template_path), daemon=True).start()
    return jsonify(jobId=job_id)


@app.post("/start-article-draft")
def start_article_draft():
    """Start twelve independent weekly briefs, returning live partial results."""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error="기사 작업 요청 형식을 확인해 주세요."), 400
    try:
        report_date = date.fromisoformat(str(payload.get("reportDate", "")))
        request_id = _article_request_id(payload)
    except ValueError:
        return jsonify(error="보고 기준일 또는 기사 작업 식별자를 확인해 주세요."), 400
    with ARTICLE_JOBS_LOCK:
        _prune_article_cancellations()
        if request_id in ARTICLE_CANCELLED_REQUESTS:
            return jsonify(status="cancelled", error="새로고침으로 중지된 기사 요청입니다. 다시 시작해 주세요."), 409
        if request_id:
            for identity, job in ARTICLE_JOBS.items():
                if job.get("_requestId") == request_id:
                    return jsonify(jobId=identity), 202
        # Do not compete for the same local model or duplicate upstream requests.
        if any(job["status"] == "cancelling" for job in ARTICLE_JOBS.values()):
            return jsonify(error="이전 기사 작업을 중지하고 있습니다. 종료 후 다시 실행해 주세요."), 409
        if any(job["status"] == "running" for job in ARTICLE_JOBS.values()):
            return jsonify(error="기사 초안이 이미 실행 중입니다. 완료 후 다시 실행해 주세요."), 409
        for identity in list(ARTICLE_JOBS):
            if len(ARTICLE_JOBS) < 16:
                break
            if ARTICLE_JOBS[identity]["status"] not in ("running", "cancelling"):
                del ARTICLE_JOBS[identity]
        job_id = uuid4().hex
        ARTICLE_JOBS[job_id] = {"status": "running", "stage": 1, "progress": 0,
                              "message": "12개 항목의 주간 기사 수집 준비 중",
                              "sections": {spec.key: {"label": spec.label, "article": None, "errors": [], "status": "finding"}
                                           for group in SECTION_GROUPS for spec in group["sections"]},
                              "startedAt": monotonic(), "reportDate": report_date.isoformat(), "totalCount": 12,
                              "_requestId": request_id, "_cancelEvent": Event()}
    Thread(target=_run_article_job, args=(job_id, report_date), daemon=True).start()
    return jsonify(jobId=job_id), 202


@app.post("/cancel-article-draft")
def cancel_article_draft():
    """Cancel only the request owned by this browser tab, including late starts."""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error="기사 작업 요청 형식을 확인해 주세요."), 400
    try:
        request_id = _article_request_id(payload)
        if not request_id:
            raise ValueError("Missing request ID")
    except ValueError:
        return jsonify(error="기사 작업 식별자를 확인해 주세요."), 400
    with ARTICLE_JOBS_LOCK:
        _prune_article_cancellations()
        ARTICLE_CANCELLED_REQUESTS[request_id] = monotonic()
        for identity, job in ARTICLE_JOBS.items():
            if job.get("_requestId") != request_id:
                continue
            if job["status"] in ("running", "cancelling"):
                job["_cancelEvent"].set()
                job.update(status="cancelling", message="새로고침 · 기존 기사 요청 종료 대기 중")
            return jsonify(jobId=identity, status=job["status"])
    # Idempotent beacon, no job yet or server restarted: reset is already safe.
    return jsonify(status="cancelled")


def _describe_article_outcome(result: dict[str, object]) -> dict[str, object]:
    """Processing finished does not mean that all twelve drafts succeeded."""
    sections = result.get("sections", {})
    counts = {"source": 0, "summary": 0, "model": 0}
    ready = 0
    for section in sections.values():
        if section.get("summary"):
            ready += 1
        elif section.get("status") == "model_unavailable":
            counts["model"] += 1
        elif section.get("article"):
            counts["summary"] += 1
        else:
            counts["source"] += 1
    total = result.get("totalCount", len(sections))
    message = f"기사 확인 종료 · 초안 {ready}/{total}건 완료"
    for key, label in (("source", "원문 미확보"), ("summary", "요약 검증 미완료"), ("model", "AI 사용 불가")):
        if counts[key]:
            message += f" · {label} {counts[key]}건"
    return {**result, "readyCount": ready, "failureCounts": counts,
            "message": message + ". 완성된 문구도 원문 검토 후 사용하세요."}


def _run_article_job(job_id: str, report_date: date):
    with ARTICLE_JOBS_LOCK:
        cancel_event = ARTICLE_JOBS[job_id]["_cancelEvent"]

    def update(**values):
        with ARTICLE_JOBS_LOCK:
            job = ARTICLE_JOBS[job_id]
            if cancel_event.is_set():
                raise ArticleDraftCancelled("기사 작업을 중지했습니다.")
            values["progress"] = max(float(job["progress"]), float(values.get("progress", job["progress"])))
            values["stage"] = max(int(job["stage"]), int(values.get("stage", job["stage"])))
            job.update(values)
    outcome = {}
    try:
        result = collect_weekly_livestock_report_draft(report_date, progress=update, cancel_event=cancel_event)
        result = _describe_article_outcome(result)
        outcome = dict(status="completed", progress=100, stage=3, result=result, sections=result["sections"],
                       message=result["message"], readyCount=result["readyCount"], candidatesFound=result["candidatesFound"])
    except ArticleDraftCancelled:
        pass
    except Exception:
        app.logger.exception("주간 축산 기사 초안 처리 실패")
        outcome = dict(status="failed", message="기사 초안 처리 중 오류가 발생했습니다. 완료된 항목은 화면에서 확인해 주세요.")
    finally:
        with ARTICLE_JOBS_LOCK:
            job = ARTICLE_JOBS[job_id]
            # Cancellation wins even if it races with the final model response.
            # The collector's thread pools have all drained before this point.
            if cancel_event.is_set():
                job.pop("result", None)
                job.update(status="cancelled", progress=0, stage=1, sections={}, readyCount=0, candidatesFound=0,
                           message="기사 작업을 중지하고 초기화했습니다.")
            else:
                job.update(outcome)
            job["elapsedSeconds"] = round(monotonic() - float(job["startedAt"]), 1)
            diagnostics_snapshot = dict(job)
        _save_article_job_diagnostics(job_id, diagnostics_snapshot)


def _save_article_job_diagnostics(job_id: str, job: dict[str, object]) -> None:
    """Keep a small local failure record after refreshes or server restarts."""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        return
    result = job.get("result") or {}
    sections = job.get("sections") or {}
    diagnostic_keys = ("sourceSeconds", "summarySeconds", "modelCalls", "modelSeconds",
                       "alternativeAttempts", "validationReasons", "promptTokens", "generatedTokens", "styleReferences")
    profile = {"jobId": job_id, "status": job.get("status"), "reportDate": job.get("reportDate"),
               "elapsedSeconds": job.get("elapsedSeconds"), "readyCount": job.get("readyCount", 0),
               "weekStart": result.get("weekStart"), "weekEnd": result.get("weekEnd"), "sections": {}}
    for key, section in sections.items():
        article = section.get("article") or {}
        diagnostics = section.get("diagnostics") or {}
        profile["sections"][key] = {
            "status": section.get("status"), "summaryError": section.get("summaryError"),
            "summaryErrorCode": section.get("summaryErrorCode"),
            "failureReasons": section.get("failureReasons", []),
            "sourceDiagnostics": {name: value for name, value in section.get("sourceDiagnostics", {}).items()
                                  if isinstance(value, int)},
            "errors": section.get("errors", []), "summary": section.get("summary"),
            "article": {name: article.get(name) for name in ("title", "publisher", "publishedDate", "url")},
            "diagnostics": {name: diagnostics[name] for name in diagnostic_keys if name in diagnostics},
        }
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"article_diagnostics_{job_id}.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        app.logger.warning("기사 실행 진단 기록을 저장하지 못했습니다.")


@app.get("/article-draft-status/<job_id>")
def article_draft_status(job_id: str):
    with ARTICLE_JOBS_LOCK:
        job = ARTICLE_JOBS.get(job_id)
        if job is None:
            return jsonify(error="기사 초안 작업을 찾지 못했습니다. 서버 재시작 후 다시 실행해 주세요."), 404
        result = {key: value for key, value in job.items() if key != "startedAt" and not key.startswith("_")}
        result.setdefault("elapsedSeconds", round(monotonic() - float(job["startedAt"]), 1))
        return jsonify(result)


@app.get("/report-status/<job_id>")
def report_status(job_id: str):
    """진행 중인 보고서 생성 작업의 상태를 반환합니다."""
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.get(job_id)
        if job is None:
            return jsonify(error="보고서 생성 작업을 찾지 못했습니다."), 404
        response = dict(job)
        # 브라우저 탭이 절전 상태여도 서버 기준의 경과 시간은 계속 정확히 보인다.
        response["elapsedSeconds"] = _elapsed_seconds_for_job(job)
        return jsonify(response)


@app.get("/download-report/<job_id>")
def download_report(job_id: str):
    """기존 링크 호환을 위해 Excel 보고서를 내려줍니다."""
    return _download_report_artifact(job_id, "excel")


@app.get("/download-report/<job_id>/<artifact>")
def download_report_artifact(job_id: str, artifact: str):
    """완료된 Excel 또는 한글 표 현행화본을 내려줍니다."""
    return _download_report_artifact(job_id, artifact)


def _download_report_artifact(job_id: str, artifact: str):
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.get(job_id)
        if job is None or job.get("status") != "completed":
            return "아직 보고서 생성이 완료되지 않았습니다.", 409
        artifact_details = {
            "excel": ("reportPath", "reportFilename", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "hwp": ("hwpPath", "hwpFilename", "application/vnd.hancom.hwpx"),
        }.get(artifact)
        if artifact_details is None:
            return "지원하지 않는 다운로드 파일입니다.", 404
        path_key, filename_key, mimetype = artifact_details
        if not job.get(path_key) or not job.get(filename_key):
            return "요청한 파일을 만들지 못했습니다.", 404
        report_path = Path(str(job[path_key]))
        report_filename = str(job[filename_key])

    if not report_path.is_file():
        return "요청한 파일을 찾지 못했습니다.", 404

    return send_file(
        report_path,
        as_attachment=True,
        download_name=report_filename,
        mimetype=mimetype,
    )


def _run_report_job(job_id: str, template_path: Path) -> None:
    """뉴스 수집과 Excel 생성을 실행하고 단계별 진행률을 기록합니다."""
    source_progress_finished: Event | None = None
    source_progress_publisher: Thread | None = None
    try:
        pending_rows = find_pending_rows(template_path, date.today())
        market_pending_rows = pending_rows["market"]
        eu_germany_rows = pending_rows["eu_germany"]
        japan_egg_rows = pending_rows["japan_egg"]
        us_egg_rows = pending_rows["us_egg"]
        us_egg_consumer_price_rows = pending_rows["us_egg_consumer_price"]
        brazil_chicken_rows = pending_rows["brazil_chicken"]
        us_chicken_rows = pending_rows["us_chicken"]
        australia_beef_rows = pending_rows["australia_beef"]
        has_pending_rows = any(
            (
                market_pending_rows,
                eu_germany_rows,
                japan_egg_rows,
                us_egg_rows,
                us_egg_consumer_price_rows,
                brazil_chicken_rows,
                us_chicken_rows,
                australia_beef_rows,
            )
        )
        # 양식 확인은 매우 짧은 내부 작업이므로 별도 단계로 표시하지 않고,
        # 원본 수집 0~59% 구간 안에서 처리한다.
        _update_job(job_id, stage=2, progress=2, message="수집 대상 확인 완료 · 원본 수집 중")
        if not has_pending_rows:
            # 이미 현행화된 Excel도 외부 사이트를 다시 조회하지 않고 다시
            # 저장한다. 이때 표의 표시 단위 기준 비교율·한글 표를 최신 로직으로
            # 반영할 수 있다.
            _update_job(
                job_id,
                stage=3,
                progress=59,
                message="새 수집 대상 없음 · Excel·HWPX 정리 중",
            )
            created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
            report_path = OUTPUT_DIR / report_filename
            _run_with_timed_progress(
                job_id,
                start_progress=59,
                ceiling_progress=82,
                expected_seconds=20,
                message="Excel 비교율과 서식 정리 중",
                action=lambda: write_market_data_to_template(
                    template_path,
                    report_path,
                    pending_rows=(),
                    market_data=(),
                        exchange_rates={},
                        chart_output_directory=report_path.with_suffix(".charts"),
                ),
            )
            _complete_job_with_hwp(job_id, report_path, report_filename, created_at)
            return
        report_dates = {date.fromisoformat(str(row["reportDate"])) for row in market_pending_rows}
        _update_job(
            job_id,
            stage=2,
            progress=2,
            message="수집 대상 확인 완료 · 해외 원자료 수집 중",
        )

        # 원본 수집은 사이트별 응답이 끝날 때만 콜백이 오므로, 이전에는 10→30%
        # 처럼 막대가 한 번에 뛰었다. 실제 수집 시간(통상 약 45초)에 맞춰 2~58%
        # 구간을 1초 단위로 완만하게 표시한다. 네트워크 요청 자체에는 영향을 주지 않는다.
        source_progress_finished = Event()
        source_progress_started = monotonic()

        def publish_source_progress() -> None:
            while not source_progress_finished.wait(1):
                elapsed_ratio = min(1.0, (monotonic() - source_progress_started) / 45)
                progress = min(58, 2 + round(56 * elapsed_ratio))
                _update_job(job_id, progress=progress)

        source_progress_publisher = Thread(target=publish_source_progress, name="source-progress", daemon=True)
        source_progress_publisher.start()

        def update_ocr_progress(index: int, total: int, report_date: date, stage: str) -> None:
            completed_count = index - 1 if stage == "started" else index
            # USMEF 분석은 전체 작업의 한 단계입니다. 이후에도 AHDB, USDA,
            # 원본 수집은 전체 작업의 약 65%를 차지한다. 이후 Excel 반영과
            # HWPX 생성 시간도 진행률에 충분히 반영되도록 10~30%만 사용한다.
            message = (
                f"뉴스라인 {index}/{total}건을 분석하고 있습니다. ({report_date:%Y-%m-%d})"
                if stage == "started"
                else f"뉴스라인 {index}/{total}건 분석을 완료했습니다. ({report_date:%Y-%m-%d})"
            )
            _update_job(
                job_id,
                message=message,
            )

        # 서로 다른 기관의 원자료는 서로 의존하지 않는다. 이전에는 이 요청들을
        # 하나씩 끝낼 때까지 기다렸기 때문에, 최신 1주만 채워도 응답 시간이 모두
        # 합산됐다. 사이트별 요청은 제한된 작업자 수로 병렬 처리하되, Excel COM
        # 저장과 HWPX 생성은 아래에서 계속 단일 순서로 처리한다.
        initial_tasks: dict[object, tuple[str, str]] = {}
        initial_results: dict[str, object] = {}
        brazil_chicken_dates = {date.fromisoformat(str(row["weekEnded"])) for row in brazil_chicken_rows}
        previous_month_start = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        graph_price_dates = {previous_month_start + timedelta(days=offset)
                             for offset in range((date.today() - previous_month_start).days + 1)}
        # 기관별 요청은 서로 독립이고, CEPEA는 별도로 제어한다. 한 번에 5개만
        # 병렬화해 최신 주차에서 느린 한 기관이 전체 수집을 막지 않으면서도
        # 외부 기관에 과도한 동시 요청을 보내지 않는다.
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="market-source") as executor:
            if report_dates:
                initial_tasks[
                    executor.submit(fetch_market_data_for_report_dates, report_dates, update_ocr_progress)
                ] = ("market", "USMEF 뉴스라인")
            if CEPEA_COLLECTION_ENABLED:
                # Independent CEPEA work no longer waits for all other sources.
                initial_tasks[executor.submit(
                    fetch_cepea_brazil_chicken_prices, brazil_chicken_dates | graph_price_dates,
                )] = ("brazilChicken", "CEPEA 브라질 닭고기")
            if eu_germany_rows:
                eu_germany_dates = {date.fromisoformat(str(row["weekEnded"])) for row in eu_germany_rows}
                initial_tasks[
                    executor.submit(fetch_ahdb_germany_pig_prices, eu_germany_dates)
                ] = ("euGermany", "AHDB 독일 돼지고기 가격")
            if japan_egg_rows:
                japan_egg_dates = {date.fromisoformat(str(row["priceDate"])) for row in japan_egg_rows}
                initial_tasks[
                    executor.submit(fetch_jz_tokyo_egg_prices, japan_egg_dates)
                ] = ("japanEgg", "JA 전농타마고 도쿄 M란 기준치")
            if us_egg_rows:
                us_egg_dates = {date.fromisoformat(str(row["weekEnded"])) for row in us_egg_rows}
                initial_tasks[
                    executor.submit(fetch_usda_us_egg_data, us_egg_dates)
                ] = ("usEgg", "USDA 미국 계란")
            if us_egg_consumer_price_rows:
                consumer_price_months = {date.fromisoformat(str(row["month"])) for row in us_egg_consumer_price_rows}
                initial_tasks[
                    executor.submit(fetch_fred_us_egg_consumer_prices, consumer_price_months)
                ] = ("usEggConsumerPrice", "FRED 미국 계란 소비자가격")
            if us_chicken_rows:
                us_chicken_dates = {date.fromisoformat(str(row["weekEnded"])) for row in us_chicken_rows}
                initial_tasks[
                    executor.submit(fetch_usda_us_chicken_data, us_chicken_dates)
                ] = ("usChicken", "USDA 미국 닭고기")
            if australia_beef_rows:
                australia_beef_dates = {date.fromisoformat(str(row["weekEnded"])) for row in australia_beef_rows}
                initial_tasks[
                    executor.submit(fetch_mla_australia_cattle_data, australia_beef_dates)
                ] = ("australiaBeef", "MLA 호주 소고기")

            if initial_tasks:
                _update_job(
                    job_id,
                    message=f"{len(initial_tasks)}개 해외 원자료를 동시에 확인하고 있습니다.",
                )
                completed_sources = 0
                for future in as_completed(initial_tasks):
                    key, label = initial_tasks[future]
                    try:
                        initial_results[key] = future.result()
                    except RuntimeError:
                        if key != "brazilChicken":
                            raise
                        initial_results[key] = {}
                        _update_job(job_id, message="CEPEA 접속 불가 · 브라질 값은 이번 실행에서 보류")
                    completed_sources += 1
                    _update_job(
                        job_id,
                        message=f"{label} 확인을 마쳤습니다. ({completed_sources}/{len(initial_tasks)})",
                    )

        market_data = list(initial_results.get("market", []))
        available_market_dates = {item["구분"] for item in market_data}
        market_pending_rows = [
            row
            for row in market_pending_rows
            if date.fromisoformat(str(row["reportDate"])) in available_market_dates
        ]
        eu_germany_prices = dict(initial_results.get("euGermany", {}))
        japan_egg_prices = dict(initial_results.get("japanEgg", {}))
        japan_egg_rows = [
            row
            for row in japan_egg_rows
            if date.fromisoformat(str(row["priceDate"])) in japan_egg_prices
        ]
        us_egg_dates = {date.fromisoformat(str(row["weekEnded"])) for row in us_egg_rows}
        us_egg_data = dict(initial_results.get("usEgg", {}))
        unpublished_us_egg_dates = us_egg_dates - set(us_egg_data)
        us_egg_rows = [
            row
            for row in us_egg_rows
            if date.fromisoformat(str(row["weekEnded"])) in us_egg_data
        ]
        if unpublished_us_egg_dates:
            deferred_dates = ", ".join(item.isoformat() for item in sorted(unpublished_us_egg_dates))
            _update_job(job_id, message="USDA 미국 계란 가격 미게시 · 이번 실행에서 보류")
        us_egg_consumer_prices = dict(initial_results.get("usEggConsumerPrice", {}))
        us_egg_consumer_price_rows = [
            row
            for row in us_egg_consumer_price_rows
            if date.fromisoformat(str(row["month"])) in us_egg_consumer_prices
        ]
        us_chicken_prices = dict(initial_results.get("usChicken", {}))
        us_chicken_rows = [
            row
            for row in us_chicken_rows
            if date.fromisoformat(str(row["weekEnded"])) in us_chicken_prices
        ]
        australia_beef_data = dict(initial_results.get("australiaBeef", {}))
        australia_beef_rows = [
            row
            for row in australia_beef_rows
            if date.fromisoformat(str(row["weekEnded"])) in australia_beef_data
        ]
        if CEPEA_COLLECTION_ENABLED:
            all_brazil_prices = dict(initial_results.get("brazilChicken", {}))
            brazil_chicken_prices = {item_date: price for item_date, price in all_brazil_prices.items()
                                     if item_date in brazil_chicken_dates}
            brazil_chicken_rows = [row for row in brazil_chicken_rows
                                   if date.fromisoformat(str(row["weekEnded"])) in brazil_chicken_prices]
            brazil_chicken_graph_prices = {
                item_date: price for item_date, price in all_brazil_prices.items()
                if previous_month_start <= item_date <= date.today()
            }
        else:
            brazil_chicken_prices = {}
            brazil_chicken_rows = []
            brazil_chicken_graph_prices = {}
            _update_job(
                job_id,
                message="브라질 닭고기 수집은 현재 일시 중지됨",
            )
        _update_job(job_id, message="날짜별 환율 수집 중")
        exchange_dates = {date.fromisoformat(str(row["exchangeDate"])) for row in market_pending_rows}
        exchange_dates.update(date.fromisoformat(str(row["exchangeDate"])) for row in us_egg_rows)
        euro_exchange_dates = {date.fromisoformat(str(row["euroExchangeDate"])) for row in eu_germany_rows}
        japan_egg_exchange_dates = {date.fromisoformat(str(row["exchangeDate"])) for row in japan_egg_rows}
        brazil_chicken_exchange_dates = {date.fromisoformat(str(row["exchangeDate"])) for row in brazil_chicken_rows}
        australia_beef_exchange_dates = {date.fromisoformat(str(row["exchangeDate"])) for row in australia_beef_rows}

        # 동일한 환율 API라도 통화별 URL과 날짜 집합은 독립적이다. 한 통화를
        # 기다린 뒤 다음 통화를 요청하지 않고, 최대 4개 요청만 동시에 보낸다.
        exchange_tasks: dict[object, tuple[str, str]] = {}
        exchange_results: dict[str, object] = {}
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="exchange-rate") as executor:
            if exchange_dates:
                exchange_tasks[executor.submit(fetch_usd_krw_exchange_rates, exchange_dates)] = ("usd", "USD/KRW")
            if euro_exchange_dates:
                exchange_tasks[executor.submit(fetch_eur_krw_exchange_rates, euro_exchange_dates)] = ("eur", "EUR/KRW")
            if japan_egg_exchange_dates:
                exchange_tasks[executor.submit(fetch_jpy_krw_exchange_rates, japan_egg_exchange_dates)] = ("jpy", "JPY/KRW")
            if brazil_chicken_exchange_dates:
                exchange_tasks[executor.submit(fetch_brl_krw_exchange_rates, brazil_chicken_exchange_dates)] = ("brl", "BRL/KRW")
            if australia_beef_exchange_dates:
                exchange_tasks[executor.submit(fetch_aud_krw_exchange_rates, australia_beef_exchange_dates)] = ("aud", "AUD/KRW")

            completed_exchanges = 0
            for future in as_completed(exchange_tasks):
                key, label = exchange_tasks[future]
                exchange_results[key] = future.result()
                completed_exchanges += 1
                _update_job(
                    job_id,
                    message=f"{label} 매매기준율을 확인했습니다. ({completed_exchanges}/{len(exchange_tasks)})",
                )

        exchange_rates = dict(exchange_results.get("usd", {}))
        market_pending_rows = [
            row
            for row in market_pending_rows
            if date.fromisoformat(str(row["exchangeDate"])) in exchange_rates
        ]
        us_egg_rows = [
            row
            for row in us_egg_rows
            if date.fromisoformat(str(row["exchangeDate"])) in exchange_rates
        ]
        eur_exchange_rates = dict(exchange_results.get("eur", {}))
        jpy_exchange_rates = dict(exchange_results.get("jpy", {}))
        japan_egg_rows = [
            row
            for row in japan_egg_rows
            if date.fromisoformat(str(row["exchangeDate"])) in jpy_exchange_rates
        ]
        brl_exchange_rates = dict(exchange_results.get("brl", {}))
        brazil_chicken_rows = [
            row
            for row in brazil_chicken_rows
            if date.fromisoformat(str(row["exchangeDate"])) in brl_exchange_rates
        ]
        aud_exchange_rates = dict(exchange_results.get("aud", {}))
        source_progress_finished.set()
        source_progress_publisher.join(timeout=0.2)
        source_progress_finished = None
        source_progress_publisher = None
        _update_job(
            job_id,
            stage=3,
            progress=59,
            message="수집한 값과 환율을 엑셀 양식에 입력하고 있습니다.",
        )
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
        def write_excel_report() -> None:
            write_market_data_to_template(
                template_path,
                report_path,
                market_pending_rows,
                market_data,
                exchange_rates,
                eu_germany_rows,
                eu_germany_prices,
                eur_exchange_rates,
                japan_egg_rows,
                japan_egg_prices,
                jpy_exchange_rates,
                us_egg_rows,
                us_egg_data,
                us_egg_consumer_price_rows,
                us_egg_consumer_prices,
                brazil_chicken_rows,
                brazil_chicken_prices,
                brl_exchange_rates,
                us_chicken_rows,
                us_chicken_prices,
                australia_beef_rows,
                australia_beef_data,
                aud_exchange_rates,
                brazil_chicken_graph_prices,
                chart_output_directory=report_path.with_suffix(".charts"),
            )

        _run_with_timed_progress(
            job_id,
            start_progress=59,
            ceiling_progress=82,
            expected_seconds=20,
            message="수집한 값과 환율을 엑셀 양식에 입력하고 있습니다.",
            action=write_excel_report,
        )
        _complete_job_with_hwp(job_id, report_path, report_filename, created_at)
    except RuntimeError as error:
        app.logger.exception("USMEF 뉴스라인 보고서 생성 실패")
        _update_job(
            job_id,
            status="failed",
            progress=0,
            message=f"보고서 생성에 실패했습니다: {error}",
            durationSeconds=_elapsed_seconds(job_id),
        )
    finally:
        if source_progress_finished is not None:
            source_progress_finished.set()
        if source_progress_publisher is not None:
            source_progress_publisher.join(timeout=0.2)
        template_path.unlink(missing_ok=True)


def _run_with_timed_progress(
    job_id: str,
    start_progress: int,
    ceiling_progress: int,
    expected_seconds: float,
    message: str,
    action: Callable[[], object],
) -> object:
    """긴 로컬 생성 단계의 실제 경과 시간에 맞춰 진행률을 완만하게 보냅니다.

    Excel COM 저장과 HWPX 압축은 중간 콜백을 제공하지 않는다. 별도 작업 스레드가
    완료 전까지만 보수적으로 진행률을 올리고, 실제 완료 시 다음 단계 또는 100%로
    넘어가므로 처리 속도에는 영향을 주지 않는다.
    """
    finished = Event()
    started_at = monotonic()

    def publish_elapsed_progress() -> None:
        while not finished.wait(1):
            elapsed_ratio = min(1.0, (monotonic() - started_at) / expected_seconds)
            progress = start_progress + round((ceiling_progress - start_progress) * elapsed_ratio)
            _update_job(job_id, progress=progress, message=message)

    publisher = Thread(target=publish_elapsed_progress, name="report-progress", daemon=True)
    publisher.start()
    try:
        return action()
    finally:
        finished.set()
        publisher.join(timeout=0.2)


def _complete_job_with_hwp(job_id: str, report_path: Path, report_filename: str, created_at: str) -> None:
    """Excel 생성 완료 후 HWPX 보고서의 표 8개와 그래프 6개를 현행화합니다."""
    _update_job(
        job_id,
        stage=4,
        progress=83,
        message="한글 HWPX 표·그래프 반영 중",
    )
    hwp_filename = f"주간_해외_수급_및_가격_동향_표현행화_{created_at}.hwpx"
    hwp_path = OUTPUT_DIR / hwp_filename
    try:
        hwp_payload = _run_with_timed_progress(
            job_id,
            start_progress=83,
            ceiling_progress=99,
            expected_seconds=15,
            message="한글 HWPX 표·그래프 반영 중",
            action=lambda: write_hwpx_table_report(
                report_path, hwp_path, chart_output_directory=report_path.with_suffix(".charts"),
            ),
        )
    except HwpReportError as error:
        # 한글 보고서 생성에 실패해도 Excel 다운로드는 유지한다.
        app.logger.warning("한글 HWPX 현행화본 생성 실패: %s", error)
        _update_job(
            job_id,
            status="completed",
            stage="done",
            progress=100,
            message="Excel 완료 · HWPX 생성 실패",
            reportPath=str(report_path),
            reportFilename=report_filename,
            hwpWarning=str(error),
            durationSeconds=_elapsed_seconds(job_id),
        )
        return

    _update_job(
        job_id,
        status="completed",
        stage="done",
        progress=100,
        message="Excel·HWPX 현행화 완료",
        reportPath=str(report_path),
        reportFilename=report_filename,
        hwpPath=str(hwp_path),
        hwpFilename=hwp_filename,
        hwpReportDate=str(hwp_payload["reportDate"]),
        durationSeconds=_elapsed_seconds(job_id),
    )


def _elapsed_seconds_for_job(job: dict[str, object]) -> int:
    """작업 시작부터 현재(또는 완료)까지의 실측 시간을 초 단위로 반환한다."""
    completed = job.get("durationSeconds")
    if isinstance(completed, (int, float)):
        return max(0, int(round(completed)))
    started_at = job.get("startedAt")
    if isinstance(started_at, (int, float)):
        return max(0, int(monotonic() - started_at))
    return 0


def _elapsed_seconds(job_id: str) -> int:
    with REPORT_JOBS_LOCK:
        return _elapsed_seconds_for_job(REPORT_JOBS.get(job_id, {}))


def _update_job(job_id: str, **changes: object) -> None:
    with REPORT_JOBS_LOCK:
        job = REPORT_JOBS.setdefault(job_id, {})
        # 병렬 수집 중 늦게 끝난 작업의 진행 메시지가 이미 표시한 진행률을
        # 뒤로 되돌리지 않도록 한다. 실패 상태는 0%를 명확히 보여야 하므로
        # 이 경우에는 예외로 둔다.
        requested_progress = changes.get("progress")
        requested_status = str(changes.get("status", job.get("status", "running")))
        if (
            isinstance(requested_progress, int)
            and requested_status == "running"
            and isinstance(job.get("progress"), int)
        ):
            changes["progress"] = max(int(job["progress"]), requested_progress)
        job.update(changes)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
