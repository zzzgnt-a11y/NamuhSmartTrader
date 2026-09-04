@echo off
chcp 65001 >nul
setlocal
set OUT=.harness_classes
if exist %OUT% rmdir /s /q %OUT%
mkdir %OUT%

echo [1/2] BudgetPolicy compile
javac -d %OUT% app\src\main\java\com\namuh\smarttrader\BudgetPolicy.java app\src\main\java\com\namuh\smarttrader\OrderGuard.java tools\BudgetPolicyHarness.java
if errorlevel 1 goto :fail

echo [2/2] BudgetPolicy negative/positive tests
java -cp %OUT% com.namuh.smarttrader.BudgetPolicyHarness
if errorlevel 1 goto :fail

echo [PASS] Harness tests completed.
exit /b 0
:fail
echo [FAIL] Harness tests failed.
exit /b 1
