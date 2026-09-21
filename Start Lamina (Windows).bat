@echo off
rem Double-click this to run Lamina on this computer. It fetches what it needs the first time (a few minutes),
rem then opens http://localhost:8000 in your browser. Closing this window stops Lamina. Nothing leaves your machine.
title Lamina
cd /d "%~dp0"
setlocal enabledelayedexpansion

where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo Lamina needs "uv" — a small tool from the makers of Ruff that fetches Python
  echo and the libraries for you. It installs into your own user folder.
  echo.
  set /p yn="Install uv now? [y/N] "
  if /i not "!yn!"=="y" (
    echo Nothing was installed. You can install uv yourself from https://docs.astral.sh/uv/
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  where uv >nul 2>nul || (
    echo uv could not be installed. Install it from https://docs.astral.sh/uv/ and run this again.
    pause
    exit /b 1
  )
)

echo Getting Lamina ready — the first time downloads Python and the libraries, so give it a few minutes.
uv sync
if errorlevel 1 (
  echo.
  echo That did not work. Copy the lines above into a bug report:
  echo https://github.com/marcelfarres/lamina/issues/new?template=bug_report.yml
  pause
  exit /b 1
)

echo.
echo Lamina is starting at http://localhost:8000 — your browser will open in a moment.
echo Leave this window open while you use it; close it to stop Lamina.
echo.
start "" cmd /c "timeout /t 6 >nul & start "" http://localhost:8000"
uv run uvicorn web.app:app --port 8000
echo.
echo Lamina has stopped. If that was not you, the port may already be in use.
pause
