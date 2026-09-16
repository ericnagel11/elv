#!/usr/bin/env bash
# Read-only probe for an approved Azure Linux host with this UAMI attached.
# No PoC imports, secret arguments, role changes, key writes or key deletion.
set -euo pipefail
set +x
umask 077

if [[ $# -ne 2 ]]; then
    echo "Usage: bash check-access.sh https://STORE.azconfig.io UAMI_CLIENT_UUID" >&2
    exit 2
fi
endpoint="$1"
client_id="$2"
# This probe is scoped to commercial Azure App Configuration, not arbitrary
# token destinations. Use the ordinary endpoint with private DNS, not privatelink.
if [[ ! "$endpoint" =~ ^https://[a-z0-9][a-z0-9-]*\.azconfig\.io/?$ ]]; then
    echo "CONFIGURATION_ERROR: supply the approved HTTPS App Configuration endpoint." >&2
    exit 2
fi
if [[ ! "$client_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ || "$client_id" == 00000000-0000-0000-0000-000000000000 ]]; then
    echo "CONFIGURATION_ERROR: supply the user-assigned identity client ID, not a secret." >&2
    exit 2
fi
if [[ "$(uname -s)" != Linux ]]; then
    echo "HOST_REQUIRED: run on approved Azure Linux compute with the identity attached." >&2
    exit 2
fi
for tool in az mktemp chmod rm grep; do
    command -v "$tool" >/dev/null || { echo "PREREQUISITE_MISSING: $tool" >&2; exit 2; }
done

# Keep the operator's Azure CLI session untouched and prohibit cached user/SPN
# fallback. A fresh login must succeed as the explicitly selected managed identity.
scratch="$(mktemp -d "${TMPDIR:-/tmp}/elv-appconfig-probe.XXXXXXXX")"
chmod 700 "$scratch"
cleanup() { rm -rf -- "$scratch"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export AZURE_CONFIG_DIR="$scratch/azure"
export AZURE_CORE_COLLECT_TELEMETRY=false
unset AZURE_APPCONFIG_CONNECTION_STRING AZURE_CLIENT_SECRET AZURE_CLIENT_CERTIFICATE_PATH AZURE_FEDERATED_TOKEN_FILE
# Bypass proxies for local identity acquisition without losing existing bypasses.
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}169.254.169.254,127.0.0.1,localhost"
export no_proxy="${no_proxy:+${no_proxy},}169.254.169.254,127.0.0.1,localhost"
error_file="$scratch/error.txt"

if ! az login --identity --client-id "$client_id" --allow-no-subscriptions \
    --output none --only-show-errors > /dev/null 2> "$error_file"; then
    echo "IDENTITY_LOGIN_FAILED: verify host attachment, approved identity use, IMDS access and Azure CLI support." >&2
    echo "No App Configuration request was attempted. Raw CLI diagnostics are not printed." >&2
    exit 3
fi

# Query at most one item's key metadata, never values, without displaying even
# the key name. A successful empty list also proves data-plane read access.
if ! az appconfig kv list --endpoint "$endpoint" --auth-mode login \
    --key '*' --label '*' --fields key --top 1 \
    --output none --only-show-errors > /dev/null 2> "$error_file"; then
    if grep -Eqi '403|forbidden' "$error_file"; then
        echo "READ_FORBIDDEN: check role scope/propagation AND network restrictions; a 403 alone does not distinguish them." >&2
    elif grep -Eqi '401|unauthorized|AADSTS' "$error_file"; then
        echo "READ_AUTHENTICATION_FAILED: verify token/tenant and the approved identity configuration." >&2
    elif grep -Eqi 'resolve|NameResolution|timed out|timeout|certificate|SSL|connection' "$error_file"; then
        echo "READ_CONNECTIVITY_FAILED: inspect private DNS, routes, firewall, proxy and approved CA trust." >&2
    else
        echo "READ_FAILED: have the host administrator investigate CLI/service compatibility and access." >&2
    fi
    echo "No configuration was changed. Raw CLI diagnostics are not printed." >&2
    exit 4
fi

echo "READ_SUCCEEDED: the explicitly selected managed identity can list key metadata from this host."
echo "An empty store is a valid result. No keys, values or tokens were displayed."
echo "Write/update/delete rights, store creation and PoC configuration alignment were NOT tested."