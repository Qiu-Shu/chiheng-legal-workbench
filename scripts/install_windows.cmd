@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_bootstrap.ps1" %*
set "install_exit=%ERRORLEVEL%"
if not "%install_exit%"=="0" pause
exit /b %install_exit%
