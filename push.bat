@echo off
setlocal
cd /d "%~dp0"
title Teryaq - GitHub Auto Push

echo ========================================================
echo          Teryaq System - GitHub Auto Push Tool
echo ========================================================
echo.

if not exist "push_to_github.py" (
    echo [X] Error: push_to_github.py not found in this folder!
    goto :end
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    py push_to_github.py
    goto :end
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python push_to_github.py
    goto :end
)

echo [X] Error: Python is not installed or not added to PATH!

:end
echo.
pause