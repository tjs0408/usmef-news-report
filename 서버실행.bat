@echo off
chcp 65001 >nul
setlocal
title Weekly Livestock Report - Local Server
cd /d "%~dp0"
if errorlevel 1 goto folder_error
if not exist ".venv\Scripts\python.exe" goto python_missing
if not exist "scripts\start_web.py" goto launcher_missing

".venv\Scripts\python.exe" -X utf8 "scripts\start_web.py" --restart --yes
set "BRIEF_LAUNCH_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %BRIEF_LAUNCH_EXIT%

:folder_error
echo 프로젝트 폴더를 열지 못했습니다. 파일을 프로젝트 폴더 안에서 실행해 주세요.
pause
exit /b 1

:python_missing
echo 프로젝트의 Python 실행 환경(.venv)이 없습니다.
echo README.md의 설치 절차를 먼저 진행해 주세요.
pause
exit /b 1

:launcher_missing
echo scripts\start_web.py 파일을 찾지 못했습니다.
echo 서버실행.bat만 옮기지 말고 프로젝트 폴더 전체를 유지해 주세요.
pause
exit /b 1
