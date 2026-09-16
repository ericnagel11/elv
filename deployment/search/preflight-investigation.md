# Investigate Search Explorer OPTIONS failure

**Latest result (2026-09-15):** After the curl OPTIONS replay returned
`HTTP=204 Remote=10.134.64.158`, the customer supplied **HTTP 200** and
**SEARCH_QUERY_SUCCEEDED** for the authenticated zero-result query on
`medical-policies-vector` at `21:53:17.327Z`, API `2026-04-01`. See the
[validation record](support-handoff.md#validate-after-the-approved-repair).
Do not repeat the successful checks. Curl does not enforce browser CORS; the
actual browser POST, other-index recovery and full PoC compatibility remain
unverified. No more generic preflight investigation is indicated by these results.

## Outcome: CMK identity failure identified

The customer initially completed the token-free replay below and received
`HTTP=500 Remote=10.134.64.158` with a Key Vault wrap/unwrap error containing
**UserAssignedIdentityNotDefined**. Search cannot obtain its configured CMK
identity `apm1081142-gld-dtpqa-01-identity` for service
`tenxeng-benefit-ai-search`. This is not a missing browser bearer token or a
reason to add wildcard CORS permissions.
The customer subsequently confirmed that the referenced identity is **not listed
on Search's User assigned Identity tab**, matching the error.

The [targeted CMK identity repair](support-handoff.md#identified-blocker-and-targeted-repair)
was provided: restore the intended existing UAMI association under **Search >
Identity > User assigned**, then verify its key-use permissions. The customer
subsequently reported OPTIONS 204 and the authenticated minimal query success
above, but has not detailed the changes made. The procedure below is retained
as the investigation record, not a request for further repetition.

## Known evidence

- Browser runs inside the customer Azure Windows VM.
- Network capture: OPTIONS preflight returns HTTP 500; the dependent POST has
  no HTTP status. This supersedes the earlier verbal identification as POST.
- Portal target observed in the preceding screenshot:
  `https://tenxeng-benefit-ai-search.search.windows.net/indexes/medical-policies-vector/docs/search?api-version=2026-05-01-preview`.
- Separate managed-identity GET/POST probes returned 500 without browser CORS.
  Their indexes/API versions differ; see [support-handoff.md](support-handoff.md).
- VM DNS/TCP tests passed to `10.134.64.158:443`. These do not establish the
  browser's actual connection, proxy/PAC selection or TLS route.
- The later OPTIONS Headers capture confirms the browser's Remote Address is
  also `10.134.64.158:443`. Response Date is `2026-09-15 20:31:50 GMT`, request ID
  `4d9e5e60-8f21-49e6-a6fc-135a582127b6`, status 500, Content-Type
  `application/json; charset=utf-8`, and advertised Content-Length 786. The user
  cannot access the body in DevTools. Exact preflight header names are now known.

The procedure below was used to examine the existing capture and obtain the
error body. The OPTIONS replay now identifies a CMK identity failure. Recovery
checks after repair are still needed to determine whether the same issue caused
the other indexes' CLI failures.

## 1. Inspect the existing OPTIONS entry

In DevTools, select the row with **Method OPTIONS / Status 500**, not the POST
row or the portal telemetry requests. Inspect the following locally. Missing
values should be reported as missing, not inferred from another request.

| Location | Evidence to collect |
| --- | --- |
| Headers > General | Remote Address and exact request URL/index/API; status is already confirmed as 500 |
| Response | Only the error code and a short redacted error message, if present; distinguish empty from "response unavailable" |
| Response Headers | `Content-Type`, `Date`, `request-id` or `x-ms-request-id`; note `Server`/`Via` if present |
| Request Headers | `Origin`, `Access-Control-Request-Method`, exact comma-separated `Access-Control-Request-Headers` (header names only) |
| Request Headers, if present | Whether `Access-Control-Request-Private-Network` is present and its value |
| Response Headers, when available | `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`, `Access-Control-Allow-Credentials`; corresponding private-network response header only if requested |

The first useful handoff is **Remote Address, Content-Type, server request ID and
redacted response error**. If the body is inaccessible, the response metadata is
still useful. DevTools showing 0 B does not establish that the server sent no
response body. The generic JavaScript stack trace is not the server error body.

Do not share Authorization/Proxy-Authorization headers, cookies, Set-Cookie,
tokens, full request headers, full screenshots, HAR exports or Copy-as-cURL
output. The name `authorization` in Access-Control-Request-Headers is not a
token; the value of an Authorization header is. An earlier screenshot exposed a
bearer token: follow the organization's exposed-token procedure and redact/remove
that image where possible. No token is needed for these preflight diagnostics.

## 2. Compare the actual browser route

- Compare Remote Address with the expected private destination
  `10.134.64.158:443`. A different value warrants DNS/proxy review, but may be an
  approved proxy rather than a misconfiguration. A matching value is a clue,
  not proof that no transparent intermediary exists.
- Inspect, without modifying, the VM's Windows/browser proxy and automatic
  configuration (PAC) settings and relevant enterprise browser policies. Unset
  HTTP_PROXY/HTTPS_PROXY environment variables do not exclude those mechanisms.
- If TLS interception is suspected, have the network owner inspect the
  connection's certificate subject/issuer and approved proxy configuration.
  An enterprise issuer alone does not prove a fault; never ignore certificate
  validation errors to make the request work.
- Use the OPTIONS request's UTC and target to locate existing gateway/proxy
  logs. JSON, HTML, a Server header or a request UUID can help attribution, but
  none independently proves which component created the 500.

## 3. Make one matched OPTIONS comparison

The exact preflight header names are now available from the customer capture.
An approved HTTP client on the same VM can send one OPTIONS request to the
**same URL/API/index** with
the same Origin, Access-Control-Request-Method and Access-Control-Request-Headers.
Include the private-network request header only if it was observed. No query
body, bearer token, API key, cookie or managed-identity login is needed; normal
browser CORS preflight is not an authenticated Search query.

Run the following in PowerShell **on the customer VM**, not the workstation.
It uses `curl.exe` explicitly (not PowerShell's `curl` alias), displays the body
locally and appends HTTP status and connected remote IP. This is a single OPTIONS
request with a 10-second connection and 30-second total timeout, no retries and
no redirect following. It does not execute the dependent POST or change resources.

```powershell
curl.exe -q --request OPTIONS --url 'https://tenxeng-benefit-ai-search.search.windows.net/indexes/medical-policies-vector/docs/search?api-version=2026-05-01-preview' `
  --header 'Origin: https://portal.azure.com' `
  --header 'Access-Control-Request-Method: POST' `
  --header 'Access-Control-Request-Headers: authorization,client-request-id,content-type,portal-controller,x-ms-client-request-id,x-ms-command-name,x-ms-operation-name' `
  --connect-timeout 10 --max-time 30 --silent --show-error `
  --write-out '\nHTTP=%{http_code} Remote=%{remote_ip}\n'
```

`-q` is deliberately first: it ignores per-user curl configuration that could
silently add credentials, redirects or extra requests. No credentials are supplied
by this command. Normal environment proxy/CA settings and certificate validation
remain in effect. If the approved network/trust setup depends on a curl config
file, obtain the equivalent approved settings before running; do not bypass it.
Curl does not automatically reproduce all browser proxy/PAC, TLS or HTTP-version
behavior. This matches the observed preflight method, URL and three relevant
headers, not every aspect of browser transport.

The curl process can exit 0 even for HTTP 500: interpret the printed HTTP status,
not just the process exit code. Share only `HTTP`, `Remote`, and any response
`error.code` plus a short redacted `error.message`. If it is HTML, describe the
error title/product rather than pasting the page. If no body is printed, report
that along with the HTTP status; do not introduce tokens to retrieve it.

Do not use the current `az rest` probe as an unauthenticated replay: it signs in
and supplies bearer authentication. Do not copy and execute the POST from
DevTools. Build only the specific OPTIONS request, preserving approved proxy/CA
settings, with a bounded timeout, no retries and no automatic redirects. Do not
disable proxy, TLS or browser security or switch to public access for comparison.
Record the client's destination and trust/proxy behavior, since a different
client does not necessarily follow the browser's route.

| Comparison result | Interpretation and next action |
| --- | --- |
| OPTIONS also returns 500 outside the browser | Failure reproduced without JavaScript/CORS enforcement. Correlate response metadata with Search/network support; service versus intermediary remains unknown. |
| OPTIONS is 2xx but allow headers do not cover the observed origin/method/header names | HTTP success is not a passed CORS check. Have the owner review the exact origin/method/header policy and supported portal behavior. |
| OPTIONS is 2xx with applicable allow headers, but browser preflight still fails | Compare exact headers, route, proxy/PAC, TLS and browser policy/timing before attributing the difference to the browser. |
| OPTIONS is 401/403 | Identify the responding component and inspect network/gateway preflight handling. Do not add a bearer token or broaden the managed identity's role to authenticate OPTIONS. |

Where credentials are involved, wildcard allow headers are not a substitute for
the required explicit authorization/origin handling. Any applicable browser
private-network checks also need to be evaluated. Do not blanket-add `*` to
index CORS, change browser flags, recreate indexes or downgrade application APIs.
An authorized owner can review relevant configuration read-only if response
evidence points to it; no CORS configuration defect has been established here.

## Exit criteria

The portal preflight is cleared only when the browser receives an acceptable
OPTIONS response and proceeds to POST. That does not prove the POST succeeds,
the portal user's query role is correct, or the VM managed-identity 500 is fixed.
Keep the existing support case evidence while investigating this new observation.

References:
- [How browser preflight works](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS#preflighted_requests)
- [Azure portal access to private Search](https://learn.microsoft.com/en-us/azure/search/service-create-private-endpoint#use-the-azure-portal-to-access-a-private-search-service)