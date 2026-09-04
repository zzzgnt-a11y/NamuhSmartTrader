@echo off
chcp 65001 >nul
setlocal
title Namuh Smart Trader WEB

echo =========================================
echo Namuh Smart Trader WEB sequential start
echo =========================================

where python >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Python 3.10+ required
  pause
  exit /b 1
)

if not exist .venv (
  echo [1/4] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :fail
)

echo [2/4] Activating environment...
call .venv\Scripts\activate.bat

echo [3/4] Installing dependencies...
python -m pip install -U pip
pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist .env (
  echo [FAIL] .env is missing.
  echo Copy .env.example to .env and enter NHPLUG_APP_KEY / NHPLUG_APP_SECRET.
  pause
  exit /b 1
)

echo [4/4] Starting web server...
python app.py
exit /b %errorlevel%

:fail
echo [FAIL] Startup failed.
pause
exit /b 1
