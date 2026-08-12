@echo off
rem ---------------------------------------------------------------------------
rem  bounty-searcher launcher
rem
rem  Double-click to open the interface in a browser. Call it from a terminal
rem  with any bounty_searcher flags to use the command line instead:
rem
rem      scan.bat --new-only --min-amount 200
rem ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

rem Degrade unencodable characters (emoji in issue titles) instead of crashing.
set "PYTHONIOENCODING=utf-8:replace"

rem The everyday defaults for the command line, used when there is no interface
rem to open. Edit this line to change them.
set "DEFAULT_SCAN=--lang typescript --lang javascript --limit 25"

rem Pause at the end only when double-clicked, not when run from a terminal.
set "PAUSE_AT_END=0"
rem Full path to find.exe -- a Unix `find` on PATH (Git Bash, WSL) shadows it.
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~nx0" >nul && set "PAUSE_AT_END=1"

rem A token raises the search limit from 10 to 30 requests/minute. Put one in
rem token.txt next to this file (it is gitignored) or set GITHUB_TOKEN yourself.
if not defined GITHUB_TOKEN (
    if exist "token.txt" set /p GITHUB_TOKEN=<token.txt
)

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python is not on your PATH.
    echo Install it from https://www.python.org/downloads/ and tick
    echo "Add python.exe to PATH" during setup.
    goto :end
)

rem The package is installed rather than imported from this folder, so this is
rem also what says whether the install is there and current.
python -c "import bounty_searcher, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -e .
    if errorlevel 1 (
        echo ERROR: could not install dependencies.
        goto :end
    )
)

rem Arguments mean the command line, exactly as before.
if not "%~1"=="" (
    python -m bounty_searcher %*
    goto :end
)

if not exist "web\dist\index.html" call :build_interface

if exist "web\dist\index.html" (
    rem One process, one port. It picks a free port and opens the browser
    rem itself, and ctrl-c here stops it.
    python -m bounty_searcher.serve
) else (
    echo Running the command line instead.
    echo.
    python -m bounty_searcher %DEFAULT_SCAN%
)
goto :end

rem ---------------------------------------------------------------------------

:build_interface
where npm >nul 2>nul
if errorlevel 1 (
    echo Node is not installed, so the interface cannot be built.
    echo Install it from https://nodejs.org/ and run this again to use it.
    exit /b 1
)
echo Building the interface. This happens once, and takes a minute.
pushd web
if not exist "node_modules" call npm install
if errorlevel 1 (
    popd
    echo ERROR: could not install the interface dependencies.
    exit /b 1
)
call npm run build
if errorlevel 1 (
    popd
    echo ERROR: could not build the interface.
    exit /b 1
)
popd
exit /b 0

:end
if "%PAUSE_AT_END%"=="1" pause
endlocal
