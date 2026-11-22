@echo off
setlocal
cd /d "%~dp0"

echo =================================================================
echo        Teryaq System - Dependencies Installer ^& Updater
echo =================================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] ERROR: Python is not installed or not added to PATH.
    echo     Please install Python 3.10+ from https://www.python.org
    echo.
    pause
    exit /b 1
)

echo [+] Python detected:
python --version
echo.

:: 2. Upgrade pip itself to ensure smooth installation
echo [+] Upgrading pip installer...
python -m pip install --upgrade pip

echo.
:: 3. Install or upgrade all dependencies from requirements.txt
if exist "requirements.txt" (
    echo [+] Installing / Updating all requirements from requirements.txt...
    python -m pip install --upgrade -r requirements.txt
) else (
    echo [X] ERROR: requirements.txt not found in current folder!
    pause
    exit /b 1
)

echo.
if %errorlevel% equ 0 (
    echo =================================================================
    echo [OK] All dependencies have been successfully installed / updated!
    echo =================================================================
) else (
    echo =================================================================
    echo [X] Warning: Some packages may have failed to install.
    echo =================================================================
)

echo.
pause
exit /b %errorlevel%
