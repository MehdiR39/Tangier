@echo off
REM Daily crypto report -> Telegram. Called by Windows Task Scheduler at 08:00.
set QRT=C:\Users\Osiris\miniconda3\envs\qrt
set REPO=C:\Users\Osiris\Documents\Tangier
"%QRT%\python.exe" "%REPO%\scripts\daily_report.py" >> "%REPO%\data_onchain\daily_report.log" 2>&1
