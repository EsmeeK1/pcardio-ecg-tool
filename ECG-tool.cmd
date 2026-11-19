@echo off
rem Start de desktop-app (zonder consolevenster). Eerst eenmalig: init_repo.cmd.
rem Mist er een pakket uit requirements.txt (bijv. na git pull)? Dan eerst init_repo.cmd: pythonw start anders stil niet.
rem ponytail: controleert alleen of elk pakket er is, niet de versie; bij een nieuwe versie-pin init_repo.cmd zelf draaien.
"%~dp0.venv\Scripts\python.exe" -c "import re,sys,importlib.metadata as m; [m.version(re.split(r'[<>=!~\[ ;]', r)[0]) for r in (l.split('#')[0].strip() for l in open(sys.argv[1], encoding='utf-8')) if r]" "%~dp0requirements.txt" 2>nul || call "%~dp0init_repo.cmd" || (pause & exit /b 1)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop\app.py"
