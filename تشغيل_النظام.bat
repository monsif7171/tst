@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo   Teryaq Cloud System - ???? ????? ?????? ?????????
echo ========================================================
echo.
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Teryaq Cloud.lnk"
set "TARGET_EXE=%~dp0PharmacySystem.exe"
set "WORKING_DIR=%~dp0"
set "ICON_FILE=%~dp0app.ico"
if not exist "%SHORTCUT_PATH%" (
    echo [+] Creating Desktop shortcut with Teryaq icon...
    powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%WORKING_DIR%'; if (Test-Path '%ICON_FILE%') { $s.IconLocation = '%ICON_FILE%' }; $s.Save()"
    echo [+] Shortcut created successfully.
)
echo [+] Starting application...
start "" "%TARGET_EXE%"
exit /b 0
