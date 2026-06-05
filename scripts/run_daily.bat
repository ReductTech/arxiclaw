@echo off
REM ============================================================
REM arxiclaw daily runner wrapper for Windows Task Scheduler
REM ============================================================
REM Edit ARXICLAW_AGENT_HOME below if you installed to a non-default
REM location. Default: %USERPROFILE%\.arxiclaw
REM ============================================================

chcp 65001 >nul
setlocal

set AGENT_HOME=%USERPROFILE%\.arxiclaw
set ARXICLAW_AGENT_HOME=%AGENT_HOME%
set ARXICLAW_BASE_URL=https://arxiclaw.reduct.cn
set PYTHONIOENCODING=utf-8

REM Find python: prefer anaconda, then PATH
set PYEXE=%USERPROFILE%\anaconda3\python.exe
if not exist "%PYEXE%" (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    set PYEXE=%%P
    goto :have_py
  )
  echo [fatal] python not found >> "%AGENT_HOME%\runs\runner.log"
  exit /b 2
)
:have_py

REM Ensure dependencies (v3.1: only requests, no LLM deps)
"%PYEXE%" -m pip show requests >nul 2>nul
if errorlevel 1 (
  echo [warn] installing requests... >> "%AGENT_HOME%\runs\runner.log"
  "%PYEXE%" -m pip install --quiet requests >> "%AGENT_HOME%\runs\runner.log" 2>&1
)

REM Run daily_runner.py
"%PYEXE%" "%AGENT_HOME%\daily_runner.py" >> "%AGENT_HOME%\runs\runner.log" 2>&1
exit /b %errorlevel%
