"""Read-only timings for sources/AI, or generate a separate local report copy.

Never logs authentication headers, prompts or secrets. This is a diagnostic CLI,
not stage-by-stage timing in the user-facing progress display.
"""
from pathlib import Path
import sys
from time import perf_counter
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from datetime import date
import json
from functools import wraps
from threading import Lock

import app
from src import overseas_article_digest as digest, hwpx_report, hwp_report
from src import template_report

measurements = []
measurement_lock = Lock()


def instrument(module, name):
    original = getattr(module, name)

    @wraps(original)
    def measured(*args, **kwargs):
        started = perf_counter()
        try:
            result = original(*args, **kwargs)
            if name == "_ollama_generate":
                print(json.dumps({"aiTokens": result.get("eval_count"),
                                  "aiEvalSeconds": round(result.get("eval_duration", 0) / 1e9, 2),
                                  "promptTokens": result.get("prompt_eval_count"),
                                  "promptSeconds": round(result.get("prompt_eval_duration", 0) / 1e9, 2),
                                  "loadSeconds": round(result.get("load_duration", 0) / 1e9, 2)}), flush=True)
            return result
        finally:
            row = {"function": name, "seconds": round(perf_counter() - started, 2)}
            with measurement_lock:
                measurements.append(row)
                print(json.dumps(row), flush=True)

    setattr(module, name, measured)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["article", "hwpx", "excel", "payload", "report"])
    parser.add_argument("--date", default="2026-09-24")
    parser.add_argument("--excel", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.excel:
        args.excel = args.excel.resolve()
    if args.output:
        args.output = args.output.resolve()
    if args.mode == "article":
        for name in ("_find_us_beef_headline", "_find_australia_beef_article",
                     "_find_domestic_beef_article", "_extract_usmef_beef_market_text",
                     "_ollama_generate"):
            instrument(digest, name)
    if args.mode == "report":
        for name in dir(app):
            if name.startswith("fetch_") or name == "_complete_job_with_hwp":
                instrument(app, name)
    for module, name in ((hwpx_report, "build_hwp_table_payload"),
                         (hwpx_report, "_download_weekly_choice_cutout_png"),
                         (hwpx_report, "_replace_excel_charts"),
                         (hwpx_report, "_download_jz_tokyo_egg_graph_png"),
                         (template_report, "_run_excel_update_script")):
        instrument(module, name)
    for run in range(args.repeat):
        started = perf_counter()
        if args.mode == "article":
            result = digest.collect_weekly_beef_report_draft(date.fromisoformat(args.date))
            print(json.dumps({"ready": {kind: bool(section.get("summary")) for kind, section in result["sections"].items()}}, ensure_ascii=False), flush=True)
        elif args.mode == "report":
            client = app.app.test_client()
            with args.excel.open("rb") as source:
                response = client.post("/start-report", data={"template_file": (source, "template.xlsx")})
            if response.status_code != 200:
                raise RuntimeError(response.get_json())
            job_id = response.get_json()["jobId"]
            while True:
                job = client.get(f"/report-status/{job_id}").get_json()
                if job["status"] in ("completed", "failed"):
                    print(json.dumps({key: job[key] for key in ("status", "message", "durationSeconds", "reportPath", "hwpPath", "hwpWarning") if key in job}, ensure_ascii=False), flush=True)
                    if job["status"] == "failed" or job.get("hwpWarning"):
                        raise RuntimeError("End-to-end generation failed; see diagnostic above")
                    break
                sleep(.5)
        elif args.mode == "payload":
            hwpx_report.build_hwp_table_payload(args.excel)
        elif args.mode == "hwpx":
            if args.output.resolve() == args.excel.resolve():
                raise ValueError("Output must not overwrite input")
            hwpx_report.write_hwpx_table_report(args.excel, args.output, chart_output_directory=args.excel.with_suffix(".charts"))
        else:
            if args.output.resolve() == args.excel.resolve():
                raise ValueError("Output must not overwrite input")
            template_report.write_market_data_to_template(args.excel, args.output, (), (), {}, chart_output_directory=args.output.with_suffix(".charts"))
        print(json.dumps({"totalSeconds": round(perf_counter() - started, 2), "run": run + 1}), flush=True)
