@echo off
rem Offline fixture: no HTTP client, no Azure CLI, no real credentials.
if not defined ELV_BLOB_TEST_LOG exit /b 99
echo CALL^|%*>>"%ELV_BLOB_TEST_LOG%"
echo CACHE^|%AZURE_CONFIG_DIR%>>"%ELV_BLOB_TEST_LOG%"
echo BYPASS^|%NO_PROXY%>>"%ELV_BLOB_TEST_LOG%"
if defined AZURE_STORAGE_KEY exit /b 98
if defined AZURE_STORAGE_SAS_TOKEN exit /b 98
if defined AZURE_STORAGE_CONNECTION_STRING exit /b 98
if defined AZURE_STORAGE_ACCOUNT exit /b 98
if defined AZURE_STORAGE_ACCOUNT_URL exit /b 98
if defined AZURE_STORAGE_SERVICE_ENDPOINT exit /b 98
if defined AZURE_STORAGE_AUTH_MODE exit /b 98
if defined AZURE_CLIENT_SECRET exit /b 98
if defined AZURE_CLIENT_CERTIFICATE_PATH exit /b 98
if defined AZURE_FEDERATED_TOKEN_FILE exit /b 98
if not "%AZURE_CORE_COLLECT_TELEMETRY%"=="false" exit /b 98
if not "%AZURE_EXTENSION_USE_DYNAMIC_INSTALL%"=="no" exit /b 98
if "%~1"=="version" (
    echo %ELV_BLOB_TEST_VERSION_JSON%
    exit /b %ELV_BLOB_TEST_VERSION_EXIT%
)
if "%~1"=="login" (
    echo ELV_TEST_PRIVATE_LOGIN_DETAIL 1>&2
    exit /b %ELV_BLOB_TEST_LOGIN_EXIT%
)
if not "%~1"=="storage" exit /b 99
if not "%~2"=="blob" exit /b 99
if not "%~3"=="list" exit /b 99
echo %ELV_BLOB_TEST_LIST_JSON%
if defined ELV_BLOB_TEST_HTTP_STATUS echo INFO: Response status: %ELV_BLOB_TEST_HTTP_STATUS% 1>&2
echo %ELV_BLOB_TEST_LIST_ERROR% 1>&2
exit /b %ELV_BLOB_TEST_LIST_EXIT%