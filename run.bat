@echo off
REM Quick launcher for zoom_live_translate
REM Usage: run.bat [--mode live|dryrun|test|beep|list-devices]

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python -m src.main %*
) else (
    python -m src.main %*
)

