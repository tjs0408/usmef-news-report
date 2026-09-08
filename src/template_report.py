"""기존 해외시장 엑셀 양식에 USMEF 수집값을 채웁니다."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_ROOT / "work"
NODE_EXECUTABLE = os.environ.get("ARTIFACT_NODE", "node")
TEMPLATE_SCRIPT = WORK_DIR / "template_report.mjs"


def find_pending_report_dates(template_path: Path, today: date) -> list[dict[str, object]]:
    """도축두수 칸이 비어 있고 발행일이 지난 양식 행을 찾습니다."""
    result = _run_template_script("pending", str(template_path), today.isoformat())
    return json.loads(result)


def write_market_data_to_template(
    template_path: Path,
    output_path: Path,
    pending_rows: Sequence[Mapping[str, object]],
    market_data: Sequence[Mapping[str, object]],
) -> None:
    """수집값을 소-미국 탭에 쓰고, 전 주 값이 같으면 USDA 수정 칸을 비웁니다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = output_path.with_suffix(".pending.json")
    market_data_path = output_path.with_suffix(".market-data.json")
    serialized_data = [
        {
            "reportDate": item["구분"].isoformat(),
            "slaughterCount": item["도축두수"],
            "previousSlaughterCount": item["usda 수정"],
            "cutoutPrice": item["미국($/lb)"],
        }
        for item in market_data
    ]
    try:
        pending_path.write_text(json.dumps(list(pending_rows)), encoding="utf-8")
        market_data_path.write_text(json.dumps(serialized_data), encoding="utf-8")
        _run_template_script(
            "fill",
            str(template_path),
            str(output_path),
            str(pending_path),
            str(market_data_path),
        )
    finally:
        pending_path.unlink(missing_ok=True)
        market_data_path.unlink(missing_ok=True)


def _run_template_script(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            [NODE_EXECUTABLE, str(TEMPLATE_SCRIPT), *arguments],
            cwd=WORK_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"엑셀 양식을 처리하지 못했습니다. ({error})") from error
    return completed.stdout
