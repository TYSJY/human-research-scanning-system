@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo [INFO] Project folder: %CD%
call :detect_python
if defined PYTHON_EXE goto :have_python

echo [INFO] No usable Python found.
echo [INFO] Trying official Python Install Manager via winget...
winget --version >nul 2>nul
if errorlevel 1 goto :no_winget

winget install 9NQ7512CXL7T -e --accept-package-agreements --disable-interactivity
if errorlevel 1 goto :winget_failed

echo.
echo [INFO] Installation command finished. Re-checking Python...
call :detect_python
if defined PYTHON_EXE goto :have_python

echo [WARN] Python may have been installed, but this window has not picked it up yet.
echo [NEXT] Close this window, then double-click this same file again.
echo.
pause
exit /b 1

:have_python
echo [OK] Found Python:
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; print('     ' + sys.executable); print('     Python ' + sys.version.split()[0])"
if errorlevel 1 goto :python_broken

echo.
echo [STEP] Preparing environment...
call install_windows.bat
if errorlevel 1 goto :install_failed

echo.
echo [STEP] Launching Research OS UI...
call start_windows.bat
exit /b %errorlevel%

:detect_python
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    goto :eof
  )
)

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.13"
  goto :eof
)
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.12"
  goto :eof
)
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.11"
  goto :eof
)
py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.10"
  goto :eof
)
py -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=py"
  goto :eof
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
  set "PYTHON_EXE=python"
  goto :eof
)
if exist "%LocalAppData%\Microsoft\WindowsApps\py.exe" (
  "%LocalAppData%\Microsoft\WindowsApps\py.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
    set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\py.exe"
    goto :eof
  )
)
if exist "%LocalAppData%\Microsoft\WindowsApps\python.exe" (
  "%LocalAppData%\Microsoft\WindowsApps\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && (
    set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\python.exe"
    goto :eof
  )
)
goto :eof

:no_winget
echo [ERROR] winget is not available on this Windows system.
echo [NEXT] Install Python 3.10+ manually, then run install_windows.bat and start_windows.bat.
echo.
pause
exit /b 1

:winget_failed
echo.
echo [ERROR] winget failed to install Python.
echo [NEXT] Open Microsoft Store or python.org, install Python 3.10+, then rerun this file.
echo.
pause
exit /b 1

:python_broken
echo.
echo [ERROR] Python was found but could not run correctly.
echo [NEXT] Close this window, open a new Command Prompt, and run: python --version
pause
exit /b 1

:install_failed
echo.
echo [ERROR] Project environment setup did not complete.
echo [NEXT] Keep the error message above and send it here.
pause
exit /b 1
