@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================
echo   AliExpress Risk Analyzer - Batch Mode
echo ============================================
echo.
echo   Input : input\
echo   Output: output\
echo.
echo   Make sure Excel files are in the input folder.
echo.
pause
echo.
aliexpress_risk_analyzer.exe --batch
echo.
echo Done. Press any key to exit...
pause >nul
