@echo off
REM Tangier Intel — continuous portfolio watcher + moonshot scanner (Robinhood Chain).
REM Same interpreter convention as run_daily_report.bat (conda env "qrt").
set QRT=C:\Users\Osiris\miniconda3\envs\qrt
set REPO=C:\Users\Osiris\Documents\Tangier
set PYTHONIOENCODING=utf-8
cd /d "%REPO%"
"%QRT%\python.exe" -m intel run %*
