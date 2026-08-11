@echo off
rem ---------------------------------------------------------------------------
rem  bounty-searcher launcher
rem
rem  Double-click to run a default scan, or call it from a terminal with any
rem  bounty_searcher flags:  scan.bat --new-only --min-amount 200
rem ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

rem Degrade unencodable characters (emoji in issue titles) instead of crashing.
set "PYTHONIOENCODING=utf-8:replace"

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

python -c "import rich, httpx" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -e .
    if errorlevel 1 (
        echo ERROR: could not install dependencies.
        goto :end
    )
)

if "%~1"=="" (
    rem Default scan: your languages, top 25, skipping anything already claimed
    rem or flagged as spam. Edit this line to change your everyday defaults.
    python -m bounty_searcher --lang typescript --lang javascript --limit 25
) else (
    python -m bounty_searcher %*
)

:end
if "%PAUSE_AT_END%"=="1" pause
endlocal
