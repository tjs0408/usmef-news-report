"""USMEF Korea 최신 뉴스라인의 소고기 지표를 Excel로 저장합니다."""

from pathlib import Path

from src.crawler import fetch_latest_market_data
from src.excel_writer import write_market_data_to_excel


def main() -> None:
    project_root = Path(__file__).resolve().parent
    output_path = project_root / "output" / "usmef_weekly_market_report.xlsx"

    market_data = fetch_latest_market_data()
    write_market_data_to_excel(market_data, output_path)

    print("최신 뉴스라인의 소고기 지표를 저장했습니다.")
    print(f"파일 위치: {output_path}")


if __name__ == "__main__":
    main()
