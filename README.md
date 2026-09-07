# USMEF 뉴스 Excel 수집기

USMEF(U.S. Meat Export Federation)의 공개 최신 뉴스 게시물을 수집해 Excel 파일로 저장하는 Python 프로그램입니다.

실행하면 `제목`, `등록일`, `링크` 열이 포함된 `output/usmef_newsline.xlsx` 파일을 만듭니다.

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

실행이 완료되면 다음 파일을 Excel로 열어 확인할 수 있습니다.

```text
output/usmef_newsline.xlsx
```

## 생성되는 Excel 파일

`USMEF 뉴스` 시트에 최신순으로 최대 100개 게시물이 저장됩니다.

- 제목
- 등록일 (`YYYY-MM-DD`)
- 링크 (클릭 가능한 원문 링크)

## 프로젝트 구조

```text
.
├── main.py
├── requirements.txt
├── README.md
├── src
│   ├── crawler.py
│   └── excel_writer.py
└── output
```

## 참고 사항

USMEF의 `Export Newsline` 아카이브는 현재 웹사이트에서 회원 전용으로 표시됩니다. 그래서 이 1단계 프로그램은 로그인 없이 이용할 수 있는 USMEF 공식 공개 뉴스 API를 사용합니다. 향후 회원 인증 정보를 사용할 수 있게 되면 `src/crawler.py`의 데이터 원본을 Export Newsline API로 교체할 수 있습니다.

USMEF 웹사이트나 API의 응답 형식이 변경되면 수집 코드도 조정해야 할 수 있습니다.

## 웹페이지로 실행하기

웹페이지에서 버튼을 눌러 보고서를 만들려면 아래 명령을 실행하세요.

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 열고 **보고서 생성 및 다운로드** 버튼을 누르면 됩니다. 웹페이지에서 생성한 파일은 기존 파일을 덮어쓰지 않도록 시간별 이름으로 `output` 폴더에 저장됩니다.

## 외부 공개 배포

이 프로젝트에는 Render 배포 설정(`render.yaml`, `Procfile`)이 포함되어 있습니다. GitHub 저장소에 올린 뒤 Render에서 해당 저장소를 연결하면 공개 웹 주소를 만들 수 있습니다. 공개 배포 시에는 Render 환경이 지정하는 `PORT`를 자동으로 사용합니다.
