@echo off
setlocal EnableExtensions

rem ===========================================================================
rem  gui.bat -- double-click to launch the breakpoint orchestration GUI
rem            (ok-ww / ok-nte)
rem
rem  Usage:
rem    gui.bat                 open the GUI (it will raise its own UAC prompt)
rem    gui.bat --dry-run       start with dry-run pre-checked
rem    gui.bat --only 8        start with "only step 8" preselected
rem    gui.bat --no-elevate    explicitly run without elevation (debugging)
rem
rem  This file may sit at the repo root or in a subfolder (e.g. launcher\):
rem  it walks up from its own location to find the folder holding gui\__main__.py.
rem
rem  NOTE ON ENCODING (this file is deliberately pure ASCII):
rem    cmd.exe parses a .bat file line by line using the *current* code page.
rem    `chcp 65001` only changes the code page for the *rest* of the run, so
rem    UTF-8 Chinese text earlier in the file gets split into garbage tokens
rem    and cmd tries to execute the fragments ("'xxx' is not recognized...").
rem    Saving the file as GBK would work on this machine but breaks on others.
rem    So: keep every byte here ASCII, and let Python print the Chinese.
rem
rem  This file is only a thin shell. All decisions (whether to elevate, how to
rem  relaunch an elevated copy) live in gui/__main__.py -- duplicating them
rem  here would drift into "bat elevated it, then python elevated it again".
rem ===========================================================================

rem ---- locate the repository root -------------------------------------------
rem  This bat may live at the repo root OR in a subfolder such as launcher\
rem  (that is where the shortcut points). So do not assume "%~dp0 IS the root";
rem  walk UP from this file until a folder that really contains gui\__main__.py
rem  shows up. Everything below is unchanged -- this only decides WHERE the
rem  repo is, every real decision still lives in gui/__main__.py.
rem  The walk ends at the drive root (a folder whose parent is itself).

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
set "ROOT="
set "PROBE=%HERE%"
set "UPSTEPS=0"

:probe_root
if exist "%PROBE%\gui\__main__.py" goto :root_found
set /a UPSTEPS+=1 >nul
if %UPSTEPS% gtr 32 goto :root_missing
for %%I in ("%PROBE%\..") do set "UP=%%~fI"
if /i "%UP%"=="%PROBE%" goto :root_missing
set "PROBE=%UP%"
goto :probe_root

:root_found
set "ROOT=%PROBE%"
cd /d "%ROOT%"

rem ---- interpreter: ONETAP_PYTHON overrides, else the project default ----
if defined ONETAP_PYTHON (
    set "PY=%ONETAP_PYTHON%"
) else (
    set "PY=D:\WORKs\Anaconda\python.exe"
)

title ok-ww / ok-nte Orchestration GUI

echo ==========================================================================
echo   ok-ww / ok-nte breakpoint orchestration - GUI
echo --------------------------------------------------------------------------
echo   repo root   : %ROOT%
echo   interpreter : %PY%
echo   args        : %*
echo --------------------------------------------------------------------------
echo   A UAC prompt will appear (both target programs are requireAdministrator).
echo   After you click Yes the GUI runs in a SEPARATE process and this black
echo   window will close immediately -- that is normal.
echo   If you click No it degrades to an unelevated run: the GUI still opens,
echo   but step 9 cannot terminate processes.
echo ==========================================================================
echo.

if not exist "%PY%" (
    echo [ERROR] Python interpreter not found:
    echo         %PY%
    echo.
    echo   The project expects D:\WORKs\Anaconda\python.exe ^(3.13.9^).
    echo   If yours lives elsewhere, set the variable first, e.g.:
    echo       set ONETAP_PYTHON=C:\path\to\python.exe
    echo       gui.bat
    echo.
    pause
    exit /b 2
)

rem ---- minimal dependency check: no tkinter means no GUI ----
"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This Python has no tkinter, the GUI cannot start:
    echo         %PY%
    echo.
    echo   The Anaconda distribution ships tkinter; stripped-down Python
    echo   builds need it installed separately.
    echo.
    pause
    exit /b 2
)

rem ---- launch. %* is forwarded verbatim ----
"%PY%" -X utf8 -m gui %*
set "RC=%ERRORLEVEL%"

rem Exit codes (see gui/__main__.py):
rem   0 = normal; the parent also returns 0 after the elevated copy takes over
rem   3 = UAC refused, degraded to an unelevated run (GUI still opened)
rem   4 = failed to import the GUI module (tkinter / dependency problem)
rem   2 = interpreter or tkinter missing (caught above already)
rem   5 = repository root not found (caught above already)

if "%RC%"=="0" goto :ok
if "%RC%"=="3" goto :degraded

echo.
echo ==========================================================================
echo   [STARTUP FAILED] exit code %RC%
echo --------------------------------------------------------------------------
echo   The GUI did not come up. Read the Python traceback above.
echo   If the elevated copy failed to start it also leaves a log at:
echo       %ROOT%\elevate-failed.log
echo ==========================================================================
echo.
if exist "%ROOT%\elevate-failed.log" (
    echo ---- elevate-failed.log ^(last 40 lines^) ----
    powershell -NoProfile -Command "Get-Content -LiteralPath '%ROOT%\elevate-failed.log' -Tail 40 -Encoding UTF8"
    echo ----------------------------------------
    echo.
)
pause
exit /b %RC%

:root_missing
echo.
echo ==========================================================================
echo   [ERROR] Cannot find the repository root
echo --------------------------------------------------------------------------
echo   Looked for a folder containing gui\__main__.py, starting at this file
echo   and walking up:
echo       %HERE%
echo.
echo   This launcher has to stay INSIDE the repository: at the repo root or in
echo   a subfolder such as launcher\ (that is where the shortcut points). A copy
echo   moved out of the repository tree cannot find the code it should start.
echo ==========================================================================
echo.
pause
exit /b 5

:degraded
echo.
echo [NOTE] Elevation was refused; the unelevated run has finished.
echo        The GUI shows a red banner: step 1 is skipped and step 9 cannot
echo        terminate processes. Re-run this bat and accept UAC when you
echo        actually need process cleanup.
timeout /t 6 >nul 2>&1
exit /b 3

:ok
rem Normal path: no pause. When elevation succeeded the GUI lives in another
rem process, so this console should disappear instead of blocking the view.
exit /b 0
