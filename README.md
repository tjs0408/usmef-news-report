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

뉴스라인 PDF는 이미지 형식이므로 프로그램은 한국어 OCR로 필요한 숫자를 읽습니다. 처음 실행할 때는 OCR 모델을 내려받기 때문에 평소보다 조금 더 걸릴 수 있습니다.

## 웹페이지로 실행하기

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 열고 **보고서 생성 및 다운로드** 버튼을 누르세요. 업로드한 양식의 비어 있는 주차 행을 찾아 다음 항목을 현행화합니다.

- `소-미국`, `돼지-미국`: 다음 주 수요일 USMEF 뉴스라인의 도축두수와 컷아웃 가격
- `돼지-EU(독일)`: AHDB 원본 Excel의 `Week ended` 날짜와 일치하는 독일 Grade E 가격(유로/100kg)

독일 가격의 `유로/kg`은 `독일 ÷ 100`으로 계산해 소수 둘째 자리까지 반올림합니다. EUR/KRW 매매기준율은 네이버 증권에서 가져오며, 주말·휴장일에는 직전 영업일 값을 사용해 원화 환산 열을 계산합니다. 생성한 파일은 브라우저 다운로드 폴더와 프로젝트의 `output` 폴더에 저장됩니다.

`usda 수정`에는 뉴스의 전 주 도축두수를 쓰되, 현재 도축두수와 같으면 빈칸으로 둡니다.

## 프로젝트 구조

```text
.
├── app.py
├── main.py
├── requirements.txt
├── README.md
├── src
│   ├── crawler.py
│   └── excel_writer.py
├── templates
│   └── index.html
└── output
```

## 참고 사항

- 원본: [USMEF Korea 뉴스라인](https://www.usmef.co.kr/main/newsline.php)
- 돼지-EU(독일) 원본: [AHDB EU deadweight pig prices](https://ahdb.org.uk/pork/eu-deadweight-pig-prices)
- 환율 원본: [네이버 증권 환율](https://stock.naver.com/marketindex/exchange/FX_EURKRW/price)
- 원본 뉴스라인의 PDF 디자인이나 표기 방식이 크게 바뀌면 OCR 추출 규칙을 조정해야 할 수 있습니다.
- Render 배포는 `render.yaml`과 `Procfile`을 사용합니다. GitHub에 반영하면 Render가 자동으로 새 버전을 배포합니다.
