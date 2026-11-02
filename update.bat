@echo off
cd /d "%~dp0"
python build_filter.py --refresh
pause
