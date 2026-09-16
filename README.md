# 주간 해외 동향 리포트

USMEF Korea 뉴스라인 1페이지의 PDF를 모두 읽어 미국 소고기 시장 데이터를 Excel 파일로 저장하는 Python 프로그램입니다.

생성되는 Excel의 열은 아래와 같습니다.

- `구분`: 뉴스라인의 발행일(최신순)
- `도축두수`: 미국 소고기 주간 도축두수(천두 단위)
- `미국($/lb)`: Choice 등급 소고기 컷아웃 가격(달러/파운드)

## 준비물

- Python 3.10 이상
- 인터넷 연결

## 설치 및 실행

PowerShell 또는 터미널에서 프로젝트 폴더로 이동한 뒤 아래 명령을 순서대로 실행하세요.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

실행이 끝나면 다음 파일이 생성됩니다.

```text
output/usmef_weekly_market_report.xlsx
```

뉴스라인 PDF는 먼저 내장 텍스트에서 필요한 숫자를 읽습니다. 텍스트가 없는 일부 이미지형 호만 한국어 OCR로 자동 전환하므로, 일반적인 주간 현행화는 훨씬 빠르게 처리됩니다. 처음 OCR이 필요한 실행에서는 모델 준비에 시간이 조금 더 걸릴 수 있습니다.

## 웹페이지로 실행하기

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 열고 **보고서 생성** 버튼을 누르세요. 업로드한 양식의 비어 있는 주차 행을 찾아 다음 항목을 현행화합니다.

- `소-미국`, `돼지-미국`: 다음 주 수요일 USMEF 뉴스라인의 도축두수와 컷아웃 가격
- `소-호주`: MLA의 주간 소 도축 합계, Eastern States Young Cattle Indicator(EYCI), AUD/KRW 환율
- `돼지-EU(독일)`: AHDB 원본 Excel의 `Week ended` 날짜와 일치하는 독일 Grade E 가격(유로/100kg)
- `계란-일본`: 주차 행의 날짜와 일치하는 JA 전농타마고 도쿄 M란 기준치(엔/kg)
- `계란-미국`: USDA Market News의 6-Area 주간 재고량과 National Shell Eggs - Caged Large 평균가격
- `닭-미국`: USDA Market News Slug ID `3208`의 Chicken (Young) 주간도축량과 Slug ID `3646`의 National Composite WOGS `Wtd Avg` 가격(cents/lb)
- `닭-브라질`: CEPEA 동결 닭고기 가격 시리즈의 동일 날짜 `À vista R$` 가격과 BRL/KRW 환율

독일 가격의 `유로/kg`은 `독일 ÷ 100`으로 계산해 소수 둘째 자리까지 반올림합니다. EUR/KRW 매매기준율은 네이버 증권에서 가져오며, 주말·휴장일에는 직전 영업일 값을 사용해 원화 환산 열을 계산합니다. 생성한 파일은 브라우저 다운로드 폴더와 프로젝트의 `output` 폴더에 저장됩니다.

### 한글 보고서 표 현행화

Excel 생성이 끝나면 같은 보고 주차(가장 최근 목요일 기준)의 값이 한글 보고서 양식의 8개 표에도 자동으로 입력됩니다.

- 소고기: 미국·호주
- 돼지고기: 미국·EU(독일)
- 육계: 미국·브라질
- 계란: 미국·일본

표 안의 `2025년`, `2026년 전주`, `2026년 이번 주`, 전주·전년 대비, 원화 환산 값만 바뀝니다. 제목, 본문 문장, 뉴스 문구, 그림과 그래프는 이번 단계에서 그대로 둡니다. 다운로드 영역에서 **Excel 현행화본**과 **한글 표 현행화본**을 각각 받을 수 있습니다.

이 기능은 로컬 Windows에서만 동작하며 아래가 필요합니다.

- 한글(Hancom Office) 2020 이상 설치
- 프로젝트의 `report_template/weekly_overseas_market_report_table_template.hwp` 양식 파일 유지

한글 프로그램이 설치되지 않은 PC 또는 Render 같은 Linux 서버에서는 Excel 생성은 가능하지만 한글 표 현행화본은 만들 수 없습니다.

계란-일본 시트는 `일본(엔/kg)`이 비어 있는 지난 주차만 찾습니다. 해당 날짜의 도쿄 M란 기준치를 입력하고, 네이버 증권의 JPY/KRW 매매기준율(100엔 기준)을 `환율(1엔=x원)` 열의 기존 양식 방식에 맞춰 입력합니다. 원화 가격은 기존 `일본(엔/kg) × 환율 ÷ 100` 계산식으로 갱신됩니다.

계란-미국 시트는 주차 행의 금요일 기준으로, 같은 주 월요일의 USDA Slug ID `1427`에서 첫 표 `Total / Total / 6-Area Total` 재고량을 가져옵니다. 같은 금요일에 발행된 Slug ID `2848`에서는 첫 표 `National Shell Eggs - Caged`의 `Large / Average Price`를 가져옵니다. USD/KRW 매매기준율을 함께 입력하며, 양식에 있던 단위·원화 환산 계산식은 그대로 유지됩니다.

닭-미국 시트는 주차 행의 날짜와 같은 날 발행된 USDA 보고서를 사용합니다. Slug ID `3208` 첫 표 `Current Day Slaughter`의 `Chicken (Young) / WTD`는 `주간도축량` 열에, Slug ID `3646` 첫 페이지 `WOG Trading by Size`의 `National Composite WOGS / Wtd Avg`는 `미국(cents/lb)` 열에 입력합니다. 천두·단위·원화 환산 등 양식에 있던 계산식은 변경하지 않습니다.

소-호주 시트는 목요일 기준일을 사용합니다. 다음 날 금요일의 MLA National Slaughter Cattle 표 `합계 / Count`를 `도축두수(두) / 호주` 열에 입력하고, 해당 목요일의 MLA EYCI를 `EYCI / 호주(센트)` 열에 입력합니다. AUD/KRW 매매기준율과 양식의 기존 천두·AUD·원화 환산 수식도 함께 갱신합니다.

닭-브라질 시트는 주차 행의 금요일과 같은 날짜를 CEPEA 동결 닭고기 가격 시리즈에서 찾아 `À vista R$`(R$/kg)만 입력합니다. BRL/KRW 매매기준율도 함께 입력하며, 양식의 기존 `브라질(R/kg) × 환율` 계산식으로 원화 가격을 갱신합니다.

소-미국의 `usda 수정`은 수정 후 값입니다. 다음 주 뉴스의 전 주 도축두수가 이전 주의 도축두수와 다를 때만, 이전 주 행의 `usda 수정` 칸에 그 값을 기록합니다.

## 프로젝트 구조

```text
.
├── app.py
├── main.py
├── requirements.txt
├── README.md
├── src
│   ├── crawler.py
│   ├── excel_writer.py
│   └── hwp_report.py
├── report_template
│   └── weekly_overseas_market_report_table_template.hwp
├── work
│   └── update_hwp_table_report.ps1
├── templates
│   └── index.html
└── output
```

## 참고 사항

- 원본: [USMEF Korea 뉴스라인](https://www.usmef.co.kr/main/newsline.php)
- 소-호주 원본: [MLA Statistics API](https://www.mla.com.au/prices-markets/statistics/api/)
- 돼지-EU(독일) 원본: [AHDB EU deadweight pig prices](https://ahdb.org.uk/pork/eu-deadweight-pig-prices)
- 계란-일본 원본: [JA 전농타마고 계란 시세](https://www.jz-tamago.co.jp/business/souba/)
- 계란-미국 원본: [USDA Market News 보고서 아카이브](https://mymarketnews.ams.usda.gov/filerepo/reports)
- 닭-브라질 원본: [CEPEA Frango 가격 시리즈](https://cepea.org.br/br/indicador/series/frango.aspx?id=181)
- 환율 원본: [네이버 증권 환율](https://stock.naver.com/marketindex/exchange/FX_EURKRW/price)
- 원본 뉴스라인의 PDF 디자인이나 표기 방식이 크게 바뀌면 OCR 추출 규칙을 조정해야 할 수 있습니다.
- Render 배포는 `render.yaml`과 `Procfile`을 사용합니다. GitHub에 반영하면 Render가 자동으로 새 버전을 배포합니다.
