@echo off
cd /d "%~dp0"
python build_filter.py --config config_standard.toml
pause
