"""USMEF Korea 주간 해외 동향 Excel 보고서를 생성하는 웹 애플리케이션입니다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
from threading import Lock, Thread
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from src.crawler import (
    fetch_ahdb_germany_pig_prices,
    fetch_aud_krw_exchange_rates,
    fetch_brl_krw_exchange_rates,
    fetch_cepea_brazil_chicken_prices,
    fetch_eur_krw_exchange_rates,
    fetch_jpy_krw_exchange_rates,
    fetch_jz_tokyo_egg_prices,
    fetch_market_data_for_report_dates,
    fetch_mla_australia_cattle_data,
    fetch_usda_us_chicken_data,
    fetch_usda_us_egg_data,
    fetch_usd_krw_exchange_rates,
)
from src.template_report import (
    find_pending_brazil_chicken_rows,
    find_pending_australia_beef_rows,
    find_pending_eu_germany_rows,
    find_pending_japan_egg_rows,
    find_pending_report_dates,
    find_pending_us_chicken_rows,
    find_pending_us_egg_rows,
    write_market_data_to_template,
)
from src.hwp_report import HwpReportError
from src.hwpx_report import write_hwpx_table_report


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
# CEPEA가 봇 탐지로 접속을 제한하는 동안에는 가격 시리즈 요청을 보내지 않는다.
# 재개 시 True로 변경하면 닭-브라질 및 브라질그래프 수집을 다시 수행한다.
CEPEA_COLLECTION_ENABLED = False

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
    try:
        market_pending_rows = find_pending_report_dates(template_path, date.today())
        eu_germany_rows = find_pending_eu_germany_rows(template_path, date.today())
        japan_egg_rows = find_pending_japan_egg_rows(template_path, date.today())
        us_egg_rows = find_pending_us_egg_rows(template_path, date.today())
        brazil_chicken_rows = find_pending_brazil_chicken_rows(template_path, date.today())
        us_chicken_rows = find_pending_us_chicken_rows(template_path, date.today())
        australia_beef_rows = find_pending_australia_beef_rows(template_path, date.today())
        has_pending_rows = any(
            (
                market_pending_rows,
                eu_germany_rows,
                japan_egg_rows,
                us_egg_rows,
                brazil_chicken_rows,
                us_chicken_rows,
                australia_beef_rows,
            )
        )
        if not has_pending_rows:
            # 이미 현행화된 Excel도 외부 사이트를 다시 조회하지 않고 다시
            # 저장한다. 이때 표의 표시 단위 기준 비교율·한글 표를 최신 로직으로
            # 반영할 수 있다.
            _update_job(
                job_id,
                progress=18,
                message="새로 수집할 빈 주차는 없습니다. 업로드된 Excel의 비교율과 한글 표를 최신 기준으로 정리하고 있습니다.",
            )
            created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
            report_path = OUTPUT_DIR / report_filename
            write_market_data_to_template(
                template_path,
                report_path,
                pending_rows=(),
                market_data=(),
                exchange_rates={},
            )
            _complete_job_with_hwp(job_id, report_path, report_filename, created_at)
            return
        report_dates = {date.fromisoformat(str(row["reportDate"])) for row in market_pending_rows}
        _update_job(
            job_id,
            progress=10,
            message=(
                f"USMEF 뉴스 {len(report_dates)}건, AHDB 독일 가격 대상 {len(eu_germany_rows)}건, "
                f"일본 계란 가격 대상 {len(japan_egg_rows)}건, 미국 계란 가격 대상 {len(us_egg_rows)}건, "
                f"브라질 닭고기 가격 대상 {len(brazil_chicken_rows)}건, 미국 닭고기 가격 대상 {len(us_chicken_rows)}건, "
                f"호주 소고기 대상 {len(australia_beef_rows)}건을 찾았습니다."
            ),
        )

        def update_ocr_progress(index: int, total: int, report_date: date, stage: str) -> None:
            completed_count = index - 1 if stage == "started" else index
            # USMEF 분석은 전체 작업의 한 단계입니다. 이후에도 AHDB, USDA,
            # MLA, CEPEA, 환율 조회와 Excel 저장이 이어지므로 여기서 70%까지
            # 올라가지 않도록 실제 작업 비중에 맞춰 12~35% 구간만 사용합니다.
            progress = 12 + round(completed_count / total * 23)
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

        # 서로 다른 기관의 원자료는 서로 의존하지 않는다. 이전에는 이 요청들을
        # 하나씩 끝낼 때까지 기다렸기 때문에, 최신 1주만 채워도 응답 시간이 모두
        # 합산됐다. 사이트별 요청은 제한된 작업자 수로 병렬 처리하되, Excel COM
        # 저장과 HWPX 생성은 아래에서 계속 단일 순서로 처리한다.
        initial_tasks: dict[object, tuple[str, str]] = {}
        initial_results: dict[str, object] = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-source") as executor:
            if report_dates:
                initial_tasks[
                    executor.submit(fetch_market_data_for_report_dates, report_dates, update_ocr_progress)
                ] = ("market", "USMEF 뉴스라인")
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
                    progress=12,
                    message=f"{len(initial_tasks)}개 해외 원자료를 동시에 확인하고 있습니다.",
                )
                completed_sources = 0
                for future in as_completed(initial_tasks):
                    key, label = initial_tasks[future]
                    initial_results[key] = future.result()
                    completed_sources += 1
                    _update_job(
                        job_id,
                        progress=35 + round(completed_sources / len(initial_tasks) * 42),
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
            _update_job(job_id, progress=78, message=f"USDA 미국 계란 가격 보고서가 아직 게시되지 않아 이번 실행에서는 건너뜁니다. ({deferred_dates})")
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
            _update_job(job_id, progress=73, message="CEPEA 브라질 닭고기 가격 시리즈의 À vista R$ 값을 확인하고 있습니다.")
            brazil_chicken_dates = {date.fromisoformat(str(row["weekEnded"])) for row in brazil_chicken_rows}
            current_month_start = date.today().replace(day=1)
            previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
            graph_price_dates = {
                previous_month_start + timedelta(days=offset)
                for offset in range((date.today() - previous_month_start).days + 1)
            }
            try:
                # 주간 표와 브라질그래프는 같은 CEPEA 가격 파일을 사용한다.
                # 두 요청을 합쳐 파일 다운로드·Excel COM 읽기를 한 번으로 줄인다.
                all_brazil_prices = fetch_cepea_brazil_chicken_prices(brazil_chicken_dates | graph_price_dates)
                brazil_chicken_prices = {
                    item_date: price
                    for item_date, price in all_brazil_prices.items()
                    if item_date in brazil_chicken_dates
                }
                brazil_chicken_rows = [
                    row
                    for row in brazil_chicken_rows
                    if date.fromisoformat(str(row["weekEnded"])) in brazil_chicken_prices
                ]
                brazil_chicken_graph_prices = {
                    item_date: price
                    for item_date, price in all_brazil_prices.items()
                    if previous_month_start <= item_date <= date.today()
                }
            except RuntimeError:
                # CEPEA의 봇 방지·일시 장애로 가격 파일에 접근하지 못해도 다른
                # 국가 보고서는 생성한다. 브라질 빈칸은 다음 실행에서 재시도된다.
                brazil_chicken_prices = {}
                brazil_chicken_rows = []
                brazil_chicken_graph_prices = {}
                _update_job(
                    job_id,
                    progress=82,
                    message="CEPEA 브라질 가격 사이트에 접속하지 못해 이번 실행에서는 브라질 값만 건너뜁니다.",
                )
        else:
            brazil_chicken_prices = {}
            brazil_chicken_rows = []
            brazil_chicken_graph_prices = {}
            _update_job(
                job_id,
                progress=82,
                message="CEPEA 브라질 닭고기 수집은 봇 탐지 방지를 위해 일시 중지되어 있습니다.",
            )
        _update_job(job_id, progress=83, message="날짜별 통화별 매매기준율을 확인하고 있습니다.")
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
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="exchange-rate") as executor:
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
                    progress=83 + round(completed_exchanges / len(exchange_tasks) * 7),
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
        _update_job(job_id, progress=91, message="수집한 값과 환율을 엑셀 양식에 입력하고 있습니다.")
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"해외시장_수급_및_가격_동향_{created_at}.xlsx"
        report_path = OUTPUT_DIR / report_filename
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
            brazil_chicken_rows,
            brazil_chicken_prices,
            brl_exchange_rates,
            us_chicken_rows,
            us_chicken_prices,
            australia_beef_rows,
            australia_beef_data,
            aud_exchange_rates,
            brazil_chicken_graph_prices,
        )
        _complete_job_with_hwp(job_id, report_path, report_filename, created_at)
    except RuntimeError as error:
        app.logger.exception("USMEF 뉴스라인 보고서 생성 실패")
        _update_job(job_id, status="failed", progress=0, message=f"보고서 생성에 실패했습니다: {error}")
    finally:
        template_path.unlink(missing_ok=True)


def _complete_job_with_hwp(job_id: str, report_path: Path, report_filename: str, created_at: str) -> None:
    """Excel 생성 완료 후 HWPX 보고서의 표·그래프를 함께 현행화합니다."""
    _update_job(job_id, progress=96, message="현행화된 Excel 값과 USDA 미국산 지육가격 그래프를 한글 보고서에 반영하고 있습니다.")
    hwp_filename = f"주간_해외_수급_및_가격_동향_표현행화_{created_at}.hwpx"
    hwp_path = OUTPUT_DIR / hwp_filename
    try:
        hwp_payload = write_hwpx_table_report(report_path, hwp_path)
    except HwpReportError as error:
        # 한글 보고서 생성에 실패해도 Excel 다운로드는 유지한다.
        app.logger.warning("한글 HWPX 현행화본 생성 실패: %s", error)
        _update_job(
            job_id,
            status="completed",
            progress=100,
            message="Excel 보고서는 생성됐지만 한글 HWPX 현행화본은 만들지 못했습니다.",
            reportPath=str(report_path),
            reportFilename=report_filename,
            hwpWarning=str(error),
        )
        return

    _update_job(
        job_id,
        status="completed",
        progress=100,
        message="Excel 보고서와 표·USDA 그래프가 현행화된 한글 HWPX 보고서가 준비되었습니다.",
        reportPath=str(report_path),
        reportFilename=report_filename,
        hwpPath=str(hwp_path),
        hwpFilename=hwp_filename,
        hwpReportDate=str(hwp_payload["reportDate"]),
    )


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
