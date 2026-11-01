@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Minerador IA
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o ambiente pela primeira vez...
  python -m venv .venv || (echo Python nao encontrado. Instale o Python 3.10 ou mais novo em python.org & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" run.py
pause
