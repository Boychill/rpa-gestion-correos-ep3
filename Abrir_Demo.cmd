@echo off
setlocal
set "RPA_DEMO_ROOT=%~dp0"
if not exist "%RPA_DEMO_ROOT%.venv\Scripts\pythonw.exe" (
  echo Primero ejecuta scripts\setup.ps1 para preparar Python.
  pause
  exit /b 1
)
start "RPA EP3" "%RPA_DEMO_ROOT%.venv\Scripts\pythonw.exe" "%RPA_DEMO_ROOT%demo_presentacion.py"
