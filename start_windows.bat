@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "TARGET_PROJECT=%~1"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
  set "PYTHON_ARGS="
) else (
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
)

if not defined PYTHON_EXE goto :missing

echo [INFO] Working directory: %CD%
echo [INFO] Starting local UI on http://127.0.0.1:8765/
echo [INFO] If your browser does not open automatically, paste this URL manually.
echo.

if not "%TARGET_PROJECT%"=="" goto :run_specific
if not exist "projects" goto :bootstrap
for /f "delims=" %%d in ('dir /b /ad "projects" 2^>nul') do goto :run_default
goto :bootstrap

:bootstrap
echo [INFO] No local project detected. Creating a demo project first...
"%PYTHON_EXE%" %PYTHON_ARGS% -m research_os.cli quickstart --launch-ui --port 8765
if errorlevel 1 goto :error
goto :done

:run_default
"%PYTHON_EXE%" %PYTHON_ARGS% -m research_os.cli ui --port 8765
if errorlevel 1 goto :error
goto :done

:run_specific
"%PYTHON_EXE%" %PYTHON_ARGS% -m research_os.cli ui "%TARGET_PROJECT%" --port 8765
if errorlevel 1 goto :error
goto :done

:missing
echo [ERROR] Cannot find usable Python.
echo [HINT] Double-click install_windows.bat first, or install Python 3.10+.
echo.
pause
exit /b 1

:error
echo.
echo [ERROR] Launch failed.
echo [TIPS]
echo   1. Make sure Python is 3.10 or newer.
echo   2. Make sure the ZIP was fully extracted.
echo   3. If port 8765 is already in use, run this in Command Prompt:
echo      "%PYTHON_EXE%" %PYTHON_ARGS% -m research_os.cli ui --port 8766
echo.
pause
exit /b 1

:done
endlocal
exit /b 0
