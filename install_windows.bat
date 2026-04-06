@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.13"
)
if not defined PYTHON_EXE py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.12"
)
if not defined PYTHON_EXE py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.11"
)
if not defined PYTHON_EXE py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.10"
)
if not defined PYTHON_EXE py -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS="
)
if not defined PYTHON_EXE python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=python"
  set "PYTHON_ARGS="
)

if not defined PYTHON_EXE goto :missing

echo [INFO] Working directory: %CD%
echo [INFO] Using Python:
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; print('       ' + sys.executable); print('       Python ' + sys.version.split()[0])"
if errorlevel 1 goto :error

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating virtual environment...
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv"
  if errorlevel 1 goto :error
) else (
  echo [INFO] Virtual environment already exists.
)

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe was not created.
  goto :error
)

echo.
echo [OK] Environment is ready.
echo [NEXT] Double-click start_windows.bat
echo.
pause
exit /b 0

:missing
echo [ERROR] Cannot find Python 3.10 or newer.
echo [HINT] Install Python 3.10/3.11/3.12/3.13 and make sure py or python works in Command Prompt.
echo.
pause
exit /b 1

:error
echo.
echo [ERROR] Setup failed.
echo [HINT] Open Command Prompt in this folder and run install_windows.bat to keep the full error on screen.
echo.
pause
exit /b 1
