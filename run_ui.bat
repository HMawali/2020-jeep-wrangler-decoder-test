@echo off
REM Tazer JL Cockpit - one-click launcher (Windows). No pip, no npm, no build.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py run_ui.py %* & goto :eof)
python run_ui.py %*
endlocal
