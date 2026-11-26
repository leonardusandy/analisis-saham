@echo off
cd /d "%~dp0"
py -3 kumpul_lokal.py --cek 2>nul || python kumpul_lokal.py --cek
pause
