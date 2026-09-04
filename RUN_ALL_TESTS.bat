@echo off
chcp 65001 >nul
setlocal
title Namuh Smart Trader v0.4 Harness

echo [1/4] Python unit tests
python -m unittest discover -s backend\tests -v
if errorlevel 1 goto :fail

echo [2/4] Java budget/paper harness
call RUN_HARNESS_TESTS.bat
if errorlevel 1 goto :fail

echo [3/4] Android clean/test/build
call BUILD_ANDROID.bat
if errorlevel 1 goto :fail

echo [4/4] PASS
echo ALL HARNESS CHECKS PASS
pause
exit /b 0
:fail
echo FAIL
pause
exit /b 1
