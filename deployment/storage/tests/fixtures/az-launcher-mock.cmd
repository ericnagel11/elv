@echo off
rem Model Windows CLI argument forwarding, but never execute real Azure CLI.
if exist "%~dp0az-mock.cmd" (
    "%~dp0az-mock.cmd" %*
) else (
    exit /b 99
)