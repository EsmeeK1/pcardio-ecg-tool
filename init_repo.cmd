@echo off
setlocal
cd /d "%~dp0"

REM P-Cardio ECG Tool: Python 3.12.x is verplicht.
REM Dit script maakt geen projectmappen aan en wijzigt geen broncode.
set "VENV_DIR=.venv"

if not exist "requirements.txt" (
    echo [FOUT] requirements.txt ontbreekt naast dit script.
    exit /b 1
)

REM Accepteer alleen de Python 3.12-reeks, nooit een standaard-fallback.
where py >nul 2>nul
if errorlevel 1 (
    echo [FOUT] Python Launcher py niet gevonden.
    echo Installeer Python 3.12.x vanaf https://www.python.org/downloads/
    exit /b 1
)
py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [FOUT] Python 3.12.x is niet geinstalleerd of niet beschikbaar via py -3.12.
    echo Installeer Python 3.12.x en voer dit script opnieuw uit.
    exit /b 1
)

REM Controleer bestaande omgeving: een oude .venv met Python 3.8 mag niet doorlopen.
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo [FOUT] Bestaande .venv gebruikt niet Python 3.12.x.
        echo Sluit de app, verwijder .venv met: rmdir /s /q .venv
        echo Voer daarna dit script opnieuw uit.
        exit /b 1
    )
) else (
    if exist "%VENV_DIR%" (
        echo [FOUT] De map .venv bestaat al, maar bevat geen bruikbare Windows-Python.
        echo Verwijder .venv eerst met: rmdir /s /q .venv
        exit /b 1
    )
    echo [INFO] Virtuele omgeving maken met Python 3.12.x...
    py -3.12 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
)

set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
echo [INFO] Geselecteerde Python-versie:
"%VENV_PY%" --version
if errorlevel 1 goto :error

echo [INFO] pip bijwerken...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [INFO] Dependencies installeren...
"%VENV_PY%" -m pip install --only-binary=:all: -r "requirements.txt"
if errorlevel 1 goto :error

echo.
echo [KLAAR] Python 3.12.x-omgeving en dependencies zijn gereed.
echo [INFO] Activeer met: %VENV_DIR%\Scripts\activate
echo [INFO] Start je app bijvoorbeeld met: python -m streamlit run streamlit/app.py
exit /b 0

:error
echo [FOUT] Initialisatie mislukt.
exit /b 1
