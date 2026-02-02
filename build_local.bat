@echo off
title RoomBooker Builder
color 0A

echo ===================================================
echo      RoomBooker Manual Build Tool
echo ===================================================
echo.

:: 1. Python Check
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [FEHLER] Python wurde nicht gefunden!
    echo Bitte installiere Python und fuege es zum PATH hinzu.
    pause
    exit /b
)

:: 2. Abhängigkeiten installieren
echo [1/4] Installiere/Update Python Libraries...
pip install -r requirements.txt
pip install pyinstaller

:: 3. Playwright Browser laden (Wichtig für den Build)
echo.
echo [2/4] Pruefe Playwright Browser...
playwright install chromium

:: 4. Das eigentliche Build-Script starten
echo.
echo [3/4] Starte build.py...
python build.py

:: 5. Optional: Setup Wizard bauen (Inno Setup)
echo.
echo [4/4] Versuche Installer zu bauen...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer\room_booker.iss"
    echo [OK] Installer erstellt!
) else (
    echo [INFO] Inno Setup Compiler (ISCC) nicht gefunden.
    echo        Der Setup-Wizard wurde uebersprungen.
    echo        Die normale 'RoomBooker.exe' liegt im Ordner 'dist'.
)

echo.
echo ===================================================
echo      BUILD ABGESCHLOSSEN
echo ===================================================
echo.
pause
