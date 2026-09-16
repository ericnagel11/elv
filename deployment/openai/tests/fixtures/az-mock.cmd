@echo off
rem Offline fixture only: never invokes Azure CLI or any HTTP client.
if not defined ELV_OPENAI_TEST_LOG exit /b 99
echo CALL^|%*>>"%ELV_OPENAI_TEST_LOG%"
echo CACHE^|%AZURE_CONFIG_DIR%>>"%ELV_OPENAI_TEST_LOG%"
echo BYPASS^|%NO_PROXY%>>"%ELV_OPENAI_TEST_LOG%"
if defined OPENAI_API_KEY exit /b 98
if defined AZURE_OPENAI_API_KEY exit /b 98
if "%~1"=="login" (
    echo ELV_TEST_LOGIN_DIAGNOSTIC 1>&2
    exit /b %ELV_OPENAI_TEST_LOGIN_EXIT%
)
if not "%~1"=="rest" exit /b 99
:findbody
if "%~1"=="" exit /b 97
if "%~1"=="--body" goto body
shift
goto findbody
:body
set "body=%~2"
type "%body:~1%" >>"%ELV_OPENAI_TEST_LOG%"
if errorlevel 1 exit /b 97
echo.>>"%ELV_OPENAI_TEST_LOG%"
echo ELV_TEST_MODEL_OUTPUT
echo %ELV_OPENAI_TEST_REST_ERROR% 1>&2
exit /b %ELV_OPENAI_TEST_REST_EXIT%