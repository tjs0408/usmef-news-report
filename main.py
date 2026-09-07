"""USMEF 최신 뉴스 목록을 Excel 파일로 저장하는 실행 파일입니다."""

from pathlib import Path

from src.crawler import fetch_latest_news
from src.excel_writer import write_news_to_excel


def main() -> None:
    project_root = Path(__file__).resolve().parent
    output_path = project_root / "output" / "usmef_newsline.xlsx"

    news_items = fetch_latest_news()
    write_news_to_excel(news_items, output_path)

    print(f"{len(news_items)}개의 게시물을 저장했습니다.")
    print(f"파일 위치: {output_path}")


if __name__ == "__main__":
    main()
