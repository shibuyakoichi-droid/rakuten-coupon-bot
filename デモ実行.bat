@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Rakuten Coupon Bot - Offline Demo ===
echo.
python demo.py
echo.
echo === Finished. Exit code: %errorlevel% ===
echo Press any key to close this window.
pause >nul
