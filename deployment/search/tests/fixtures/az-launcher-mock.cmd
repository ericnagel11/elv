@echo off
rem Model the parenthesized IF/ELSE and argument forwarding of a Windows CLI
rem launcher, but delegate ONLY to the local mock, never Python or Azure CLI.
if exist "%~dp0az-mock.cmd" (
    "%~dp0az-mock.cmd" %*
) else (
    exit /b 99
)