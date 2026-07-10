@echo off
rem Starts your Chromium-based browser with remote debugging (CDP) enabled,
rem so the WebScout agent works in THIS window instead of opening its own.
rem
rem A dedicated profile is used because modern Chromium refuses
rem --remote-debugging-port on the default profile. Logins and cookies
rem made in this profile persist between runs.
rem
rem The WebScout extension is auto-loaded when the browser allows
rem --load-extension; otherwise install it once manually:
rem   browser://extensions -> Developer mode -> Load unpacked -> "extension" folder.

set PROFILE=%LOCALAPPDATA%\WebScoutBrowserProfile
set EXT=%~dp0extension

set BROWSER=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "BROWSER=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "C:\Program Files\Yandex\YandexBrowser\Application\browser.exe" set "BROWSER=C:\Program Files\Yandex\YandexBrowser\Application\browser.exe"
if not defined BROWSER if exist "%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe" set "BROWSER=%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe"
if not defined BROWSER if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" set "BROWSER=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if not defined BROWSER (
    echo No Chromium-based browser found ^(Chrome / Yandex / Edge^).
    pause
    exit /b 1
)

echo Starting: %BROWSER%
start "" "%BROWSER%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" --load-extension="%EXT%" --disable-extensions-except="%EXT%" --no-first-run --no-default-browser-check
