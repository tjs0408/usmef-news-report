"""USMEF 공개 뉴스 API에서 최신 게시물을 가져옵니다."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen


API_URL = "https://teamlinq.usmef.org/api/articles"
SITE_URL = "https://usmef.org"
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "USMEF-Newsline-Excel-Crawler/1.0"


def fetch_latest_news(max_items: int = 100) -> list[dict[str, str]]:
    """최신순으로 정렬된 USMEF 공개 뉴스 게시물을 반환합니다.

    API가 연도별 목록을 제공하므로, 현재 연도와 전년 데이터를 함께 요청합니다.
    연초에도 최신 글을 놓치지 않기 위한 처리입니다.
    """
    if max_items < 1:
        raise ValueError("max_items는 1 이상이어야 합니다.")

    current_year = datetime.now().year
    raw_items: list[dict[str, Any]] = []
    for year in (current_year, current_year - 1):
        raw_items.extend(_fetch_news_for_year(year))

    news_items = [_normalise_item(item) for item in raw_items]
    news_items = [item for item in news_items if item is not None]
    news_items.sort(key=lambda item: _parse_date(item["등록일"]), reverse=True)
    return news_items[:max_items]


def _fetch_news_for_year(year: int) -> list[dict[str, Any]]:
    """특정 연도의 뉴스 데이터를 API에서 가져옵니다."""
    request = Request(
        # USMEF API는 일반적인 ``?year=YYYY`` 대신
        # ``/articles&year=YYYY`` 형식을 사용합니다.
        f"{API_URL}&year={year}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("USMEF 서버가 JSON 형식의 뉴스 목록을 반환하지 않았습니다.") from error

    if not payload.get("success") or not isinstance(payload.get("data"), list):
        raise RuntimeError("USMEF 뉴스 목록을 가져오지 못했습니다.")
    return payload["data"]


def _normalise_item(item: dict[str, Any]) -> dict[str, str] | None:
    """API 응답을 Excel에 쓸 세 개의 열로 정리합니다."""
    title = str(item.get("headline", "")).strip()
    published_at = str(item.get("datePublished", "")).strip()
    relative_link = str(item.get("hrefSlug", "")).strip()
    if not title or not published_at or not relative_link:
        return None

    return {
        "제목": title,
        "등록일": _parse_date(published_at).strftime("%Y-%m-%d"),
        "링크": urljoin(SITE_URL, relative_link),
    }


def _parse_date(value: str) -> datetime:
    """USMEF API의 영문 날짜를 datetime으로 변환합니다."""
    for date_format in ("%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise RuntimeError(f"등록일 형식을 해석할 수 없습니다: {value}")
