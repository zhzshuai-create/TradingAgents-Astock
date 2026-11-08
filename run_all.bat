@echo off
REM One-click start: .env.stack picks next (8600 backend + 5173 UI + 8502 journal)
REM or legacy (8501 + 8502). --real-models only affects next and still needs
REM TA_ENABLE_REAL_RUNNER=1 in .env.
cd /d %~dp0
python scripts\stack_launch.py --real-models
