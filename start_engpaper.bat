@echo off
chcp 65001 >nul
title EngPaperTeacher
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup_engpaper.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe serve.py
pause
