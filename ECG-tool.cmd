@echo off
rem Start de desktop-app (zonder consolevenster). Eerst eenmalig: .venv aanmaken en requirements.txt installeren.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop\app.py"
