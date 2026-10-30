"""User-run Windows launcher with an opt-in, ownership-checked restart."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import webbrowser

if __package__:
    from .project_server_control import ServerControlError, inspect_server, stop_server
else:
    from project_server_control import ServerControlError, inspect_server, stop_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5002
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/"
READY_TIMEOUT_SECONDS = 30
PAGE_MARKERS = ('<title>주간 해외 동향 리포트</title>', 'id="article-summary-form"')
STATE_URL = SERVER_URL + "local-server-state"


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def port_is_open() -> bool:
    try:
        with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def is_project_page() -> bool:
    # Loopback readiness checks must not use the user's remote HTTP proxy.
    opener = build_opener(ProxyHandler({}), NoRedirects())
    request = Request(SERVER_URL, headers={"User-Agent": "WeeklyLivestockLauncher/1"})
    try:
        with opener.open(request, timeout=1.0) as response:
            if response.geturl() != SERVER_URL or response.status != 200:
                return False
            page = response.read(1024 * 1024).decode("utf-8", errors="replace")
            return all(marker in page for marker in PAGE_MARKERS)
    except (OSError, URLError, ValueError):
        return False


def open_page() -> None:
    try:
        opened = webbrowser.open(SERVER_URL, new=2)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        print(f"브라우저를 자동으로 열지 못했습니다. 직접 접속해 주세요: {SERVER_URL}")


def read_server_state() -> dict | None:
    opener = build_opener(ProxyHandler({}), NoRedirects())
    request = Request(STATE_URL, headers={"User-Agent": "WeeklyLivestockLauncher/1"})
    try:
        with opener.open(request, timeout=1.0) as response:
            if response.geturl() != STATE_URL or response.status != 200:
                return None
            state = json.loads(response.read(8192).decode("utf-8"))
    except (OSError, URLError, ValueError, UnicodeError):
        return None
    if not isinstance(state, dict):
        return None
    if not all(type(state.get(key)) is bool for key in ("busy", "articleBusy", "reportBusy")):
        return None
    if state["busy"] != (state["articleBusy"] or state["reportBusy"]):
        return None
    if type(state.get("pid")) is not int or state["pid"] <= 0:
        return None
    return state


def restart_existing_server(project_root: Path, *, automatic: bool = False) -> bool:
    """Automatic restarts require a verified idle project; legacy mode asks."""
    try:
        identities = inspect_server(project_root, port=SERVER_PORT)
    except ServerControlError as error:
        print(f"기존 서버의 프로젝트 소유 확인에 실패했습니다: {error}")
        return False
    if not identities:
        print("기존 서버가 변경됐습니다. 종료하지 않았으니 배치파일을 다시 실행해 주세요.")
        return False
    listener = next((identity for identity in identities if identity.get("role") == "listener"), None)
    if listener is None:
        print("종료할 서버의 식별 정보를 확인하지 못했습니다. 기존 서버는 건드리지 않습니다.")
        return False

    state = read_server_state()
    if state is not None:
        if state["pid"] != listener["pid"]:
            print("웹페이지와 서버 프로세스 정보가 일치하지 않아 종료하지 않습니다.")
            return False
        if state["busy"]:
            print("기사 초안 또는 보고서 작업이 진행 중입니다. 완료한 뒤 다시 실행해 주세요.")
            return False
    else:
        print("구버전 서버이거나 작업 상태를 확인할 수 없습니다.")
        if automatic:
            print("작업 중인 서버를 끄지 않도록 자동 재시작을 중단합니다. 기존 서버를 유지합니다.")
            return False
        print("기사 초안·보고서 생성·다운로드가 모두 끝난 뒤에만 재시작해 주세요.")
    print(f"이 프로젝트의 기존 서버(PID {listener['pid']})를 종료하고 현재 파일의 코드로 다시 시작합니다.")
    if automatic:
        print("실행 중인 기사·보고서 작업이 없어 확인 입력 없이 자동 재시작합니다.")
    else:
        try:
            answer = input("작업이 모두 끝났습니까? 재시작하려면 Y, 취소하려면 Enter: ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print("\n재시작을 취소했습니다. 기존 서버를 유지합니다.")
            return False
        if answer not in ("y", "yes"):
            print("재시작을 취소했습니다. 기존 서버를 유지합니다.")
            return False

    # Recheck jobs even without a human prompt, then verify PID + creation time
    # again in stop_server immediately before stopping the exact processes.
    current_state = read_server_state()
    if current_state is not None and (current_state["busy"] or current_state["pid"] != listener["pid"]):
        print("작업이 시작됐거나 서버가 변경돼 재시작을 중단합니다.")
        return False
    if state is not None and current_state is None:
        print("서버 상태를 다시 확인하지 못해 종료하지 않습니다. 잠시 후 다시 실행해 주세요.")
        return False
    try:
        stop_server(project_root, identities, port=SERVER_PORT)
    except ServerControlError as error:
        print(f"서버를 종료하지 못했습니다: {error}")
        return False

    deadline = time.monotonic() + 10
    while port_is_open():
        if time.monotonic() >= deadline:
            print("5002번 포트가 아직 사용 중입니다. 중복 실행하지 않으니 상태를 확인해 주세요.")
            return False
        time.sleep(0.25)
    print("기존 서버 종료를 확인했습니다. 새 코드를 불러옵니다.")
    return True


def run(project_root: Path = PROJECT_ROOT, *, restart_existing: bool = False, automatic_restart: bool = False) -> int:
    interpreter = project_root / ".venv" / "Scripts" / "python.exe"
    application = project_root / "app.py"
    if not interpreter.is_file() or not application.is_file():
        print("프로젝트의 .venv 또는 app.py가 없습니다. README.md의 설치 절차를 확인해 주세요.")
        return 1

    print("주간 해외 축산물 동향 웹페이지")
    print(f"접속 주소: {SERVER_URL}")
    if port_is_open():
        if not is_project_page():
            print("5002번 포트를 다른 프로그램이 사용 중이거나 기존 서버가 응답하지 않습니다.")
            print("기존 프로그램은 종료하지 않았습니다. 상태를 확인한 뒤 다시 실행해 주세요.")
            return 1
        if restart_existing:
            if not restart_existing_server(project_root, automatic=automatic_restart):
                return 1
        else:
            print("이미 실행 중인 프로젝트 서버가 있어 기존 웹페이지를 엽니다.")
            print("새 코드로 재시작한 것은 아닙니다. 재시작하려면 서버실행.bat를 실행해 주세요.")
            open_page()
            return 0

    environment = os.environ.copy()
    environment["PORT"] = str(SERVER_PORT)
    environment["PYTHONUTF8"] = "1"
    print("서버를 시작합니다. 준비되면 기본 브라우저가 열립니다.")
    print("사용하는 동안 이 창을 열어 두세요. 종료하려면 Ctrl+C를 누르세요.")
    try:
        process = subprocess.Popen(
            [str(interpreter), "-X", "utf8", str(application)],
            cwd=str(project_root),
            env=environment,
        )
    except OSError as error:
        print(f"서버 실행에 실패했습니다: {error}")
        return 1

    try:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while process.poll() is None:
            if is_project_page():
                print("서버 준비가 완료됐습니다. 웹페이지를 엽니다.")
                state = read_server_state()
                if state is not None:
                    print(f"실행 버전: {state.get('styleVersion', '확인 불가')} · PID {state['pid']}")
                open_page()
                break
            if time.monotonic() >= deadline:
                print(f"서버 준비에 시간이 걸리고 있습니다. 준비 후 직접 접속해 주세요: {SERVER_URL}")
                break
            time.sleep(0.25)
        exit_code = process.wait()
        if exit_code:
            print(f"서버가 종료됐습니다(종료 코드: {exit_code}). 위 오류 메시지를 확인해 주세요.")
        return exit_code
    except KeyboardInterrupt:
        # The visible console sends Ctrl+C to the child as well. Never force-kill it.
        print("\n서버 종료를 기다리고 있습니다.")
        try:
            return process.wait(timeout=8)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            print("서버 종료를 확인하지 못했습니다. 이 창의 상태를 확인해 주세요.")
            return 130


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the local server; verified idle servers can restart automatically.")
    parser.add_argument("--restart", action="store_true", help="verify and confirm restarting this project's existing server")
    parser.add_argument("--yes", action="store_true", help="restart without a prompt only when this project's server is verified idle")
    arguments = parser.parse_args()
    if arguments.yes and not arguments.restart:
        parser.error("--yes requires --restart")
    raise SystemExit(run(restart_existing=arguments.restart, automatic_restart=arguments.yes))
