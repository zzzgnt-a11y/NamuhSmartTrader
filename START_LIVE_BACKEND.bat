@echo off
chcp 65001 >nul
setlocal
title Namuh Smart Trader v0.4 Live Backend

echo ==========================================
echo [1/4] Python 확인
where python >nul 2>&1 || goto :no_python

echo [2/4] 가상환경 준비
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat

echo [3/4] 의존성 설치
python -m pip install -U pip
pip install -r backend\requirements.txt
if errorlevel 1 goto :fail

if not exist backend\.env (
  echo [FAIL] backend\.env 가 없습니다.
  echo backend\.env.example 을 .env 로 복사한 뒤 NHPLUG_APP_KEY / SECRET을 입력하세요.
  pause
  exit /b 1
)

echo [4/4] 실시간 백엔드 시작
python -m backend.run_server
exit /b %errorlevel%

:no_python
echo [FAIL] Python 3.10+ 필요
pause
exit /b 1

:fail
echo [FAIL] 설치 또는 실행 실패
pause
exit /b 1
