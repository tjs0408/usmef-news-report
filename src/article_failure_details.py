"""Small, public explanations of article validation failures (no model text)."""
from __future__ import annotations

from typing import Any


def summary_failure_details(error: Exception, diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Keep the actual validation cause when a bounded repair budget runs out.

    A local retry cap is not a provider quota. Only our own validation reason
    labels are exposed; prompts, generated text and HTTP errors are not copied.
    """
    reasons = []
    for rejection in diagnostics.get("validationReasons", []):
        for reason in rejection.get("reasons", []):
            reason = str(reason)
            if reason not in reasons:
                reasons.append(reason)
    name = type(error).__name__
    code = {
        "ArticleSummaryLayoutError": "summary_layout",
        "ArticleSummaryBudgetExceeded": "summary_repair_limit",
        "ArticleSummaryValidationError": "summary_validation",
    }.get(name, "summary_unavailable")
    message = str(error)
    if code == "summary_repair_limit":
        calls = int(diagnostics.get("modelCalls", 0))
        if "시간 제한" in message:
            message = "요약 교정에 할당한 처리 시간이 끝났습니다. 서비스 이용 한도 오류는 아닙니다."
        else:
            message = f"요약 교정 {calls}회에서 조건을 충족하지 못했습니다. 서비스 이용 한도 오류는 아닙니다."
        if reasons:
            message += " 확인 필요: " + " · ".join(reasons[-3:]) + "."
    return {"summaryError": message, "summaryErrorCode": code, "failureReasons": reasons}
