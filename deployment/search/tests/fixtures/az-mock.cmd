@echo off
rem Offline fixture only: never invokes Azure CLI or any HTTP client.
if not defined ELV_SEARCH_TEST_LOG exit /b 99
echo CALL^|%*>>"%ELV_SEARCH_TEST_LOG%"
echo CACHE^|%AZURE_CONFIG_DIR%>>"%ELV_SEARCH_TEST_LOG%"
echo BYPASS^|%NO_PROXY%>>"%ELV_SEARCH_TEST_LOG%"
if defined AZURE_SEARCH_API_KEY exit /b 98
if defined AZURE_SEARCH_KEY exit /b 98
if defined AZURE_CLIENT_SECRET exit /b 98
if defined AZURE_CLIENT_CERTIFICATE_PATH exit /b 98
if defined AZURE_FEDERATED_TOKEN_FILE exit /b 98
if not "%AZURE_CORE_COLLECT_TELEMETRY%"=="false" exit /b 98
if "%~1"=="version" (
    echo {"azure-cli":"2.80.0","extensions":{"ELV_TEST_PRIVATE_VALUE":"hidden"}}
    exit /b 0
)
if "%~1"=="login" (
    echo ELV_TEST_LOGIN_DIAGNOSTIC 1>&2
    exit /b %ELV_SEARCH_TEST_LOGIN_EXIT%
)
if not "%~1"=="rest" exit /b 99
if not "%~2"=="--method" exit /b 97
if not "%~3"=="get" if not "%~3"=="post" exit /b 97
if not "%~4"=="--url" exit /b 97
rem Batch positional parsing splits the URL at its equals sign. Real az.cmd
rem forwards intact %%* to Python; the harness verifies that exact CALL line,
rem including the URL, Search audience and output suppression arguments.
if "%~3"=="post" goto queryargs
:response
echo %ELV_SEARCH_TEST_COUNT%
if defined ELV_SEARCH_TEST_HTTP_STATUS echo INFO: Response status: %ELV_SEARCH_TEST_HTTP_STATUS% 1>&2
if defined ELV_SEARCH_TEST_RESPONSE_HEADERS type "%ELV_SEARCH_TEST_RESPONSE_HEADERS%" 1>&2
echo %ELV_SEARCH_TEST_REST_ERROR% 1>&2
exit /b %ELV_SEARCH_TEST_REST_EXIT%
:queryargs
if "%~1"=="" goto response
if "%~1"=="--body" goto querybody
if "%~1"=="--output-file" goto queryoutput
shift
goto queryargs
:querybody
set "body=%~2"
type "%body:~1%" >>"%ELV_SEARCH_TEST_LOG%"
if errorlevel 1 exit /b 97
echo.>>"%ELV_SEARCH_TEST_LOG%"
shift
shift
goto queryargs
:queryoutput
if "%ELV_SEARCH_TEST_REST_EXIT%"=="0" >"%~2" echo %ELV_SEARCH_TEST_QUERY_RESPONSE%
shift
shift
goto queryargs