@echo off
REM 一键启动: A股平台(8501) + 交易日志(8502, 被 iframe 嵌入)
cd /d %~dp0
python web\launch.py --with-journal
