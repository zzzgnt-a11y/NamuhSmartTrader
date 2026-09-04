@echo off
chcp 65001 >nul
setlocal
title Namuh Smart Trader Android v0.3 PAPER Build

echo ==========================================
echo Namuh Smart Trader v0.3 PAPER 순차 검증/빌드
echo ==========================================

where java >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Java/JDK가 없습니다.
  pause
  exit /b 1
)

where javac >nul 2>&1
if errorlevel 1 (
  echo [FAIL] javac가 없습니다. JDK를 설치하세요.
  pause
  exit /b 1
)

echo [1/4] HARNESS TEST
call RUN_HARNESS_TESTS.bat
if errorlevel 1 goto :fail

if exist gradlew.bat (
  set GR=gradlew.bat
) else (
  where gradle >nul 2>&1
  if errorlevel 1 (
    echo [FAIL] Gradle이 없습니다. GitHub Actions 또는 Android Studio에서 빌드하세요.
    pause
    exit /b 1
  )
  set GR=gradle
)

echo [2/4] CLEAN
call %GR% clean
if errorlevel 1 goto :fail

echo [3/4] ANDROID TEST
call %GR% test
if errorlevel 1 goto :fail

echo [4/4] APK BUILD
call %GR% :app:assembleDebug
if errorlevel 1 goto :fail

echo [PASS] app\build\outputs\apk\debug\app-debug.apk
pause
exit /b 0

:fail
echo [FAIL] 검증 또는 빌드 실패.
pause
exit /b 1
