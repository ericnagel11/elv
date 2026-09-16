#!/usr/bin/env bash
# Installs host files only. Does not start/enable services, run pip or call Azure.
set -euo pipefail
umask 027

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --apply ) ]]; then
    echo "Usage: bash deployment/redhat/install-services.sh [--apply]" >&2
    exit 2
fi
if [[ $# -eq 0 ]]; then
    echo "Plan: use /opt/elv; create two non-login service users and state directories;"
    echo "copy three systemd units; create /etc/elv/poc001.env and poc002.env only if absent;"
    echo "verify units and reload systemd. Existing configuration is preserved."
    echo "No services are started/enabled. No Azure operation is performed."
    echo "Review README.md and rerun with --apply on the approved VM."
    exit 0
fi
if [[ $(uname -s) != Linux || $EUID -ne 0 ]]; then
    echo "Applying host service installation requires an administrator on the Linux VM." >&2
    exit 2
fi
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$root" != /opt/elv ]]; then
    echo "The reviewed service layout requires the checkout at /opt/elv (not a symlink)." >&2
    exit 2
fi
for tool in systemctl systemd-analyze useradd getent install runuser; do
    command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 2; }
done
for poc in 001-config-driven-responses 002-regional-multilingual-experience; do
    [[ -x "$root/pocs/$poc/.venv/bin/python" ]] || { echo "Prepare the $poc venv first." >&2; exit 2; }
done
for id in 001 002; do
    user="elv-poc$id"
    if entry="$(getent passwd "$user")"; then
        IFS=: read -r name password uid gid comment home shell <<< "$entry"
        if [[ "$uid" == 0 || "$home" != "/var/lib/$user" || "$shell" != /sbin/nologin ]]; then
            echo "Refusing to reuse an unrelated user named $user." >&2
            exit 2
        fi
    else
        if getent group "$user" >/dev/null; then
            echo "An existing group named $user needs administrator review." >&2
            exit 2
        fi
        useradd --system --user-group --home-dir "/var/lib/$user" --shell /sbin/nologin "$user"
    fi
    [[ ! -L "/var/lib/$user" ]] || { echo "State directory must not be a symlink." >&2; exit 2; }
    install -d -o "$user" -g "$user" -m 0700 "/var/lib/$user"
done
[[ ! -L /etc/elv ]] || { echo "/etc/elv must not be a symlink." >&2; exit 2; }
install -d -o root -g root -m 0755 /etc/elv
for id in 001 002; do
    target="/etc/elv/poc$id.env"
    if [[ -L "$target" || ( -e "$target" && ! -f "$target" ) ]]; then
        echo "Refusing unexpected environment file: $target" >&2
        exit 2
    fi
    if [[ ! -e "$target" ]]; then
        install -o root -g "elv-poc$id" -m 0640 "$root/deployment/redhat/poc$id.env.example" "$target"
    else
        echo "Preserving existing $target; administrator must verify ownership and permissions."
    fi
done
# Catch filesystem access failures without importing the applications or asking
# for an Azure token. Service users must read, but must not own writable code.
for mapping in '001:001-config-driven-responses' '002:002-regional-multilingual-experience'; do
    id="${mapping%%:*}"
    project="$root/pocs/${mapping#*:}"
    for readable in "$project/app.py" "$root/deployment/redhat/run.py" "/etc/elv/poc$id.env"; do
        runuser -u "elv-poc$id" -- test -r "$readable" || { echo "elv-poc$id cannot read a required file; check deployment permissions." >&2; exit 2; }
    done
    runuser -u "elv-poc$id" -- test -x "$project/.venv/bin/python" || { echo "elv-poc$id cannot execute its venv interpreter." >&2; exit 2; }
    for protected in "$project" "$project/app.py" "$project/.venv" "$root/deployment/redhat"; do
        if runuser -u "elv-poc$id" -- test -w "$protected"; then
            echo "Application users must not have write access to source or venvs." >&2
            exit 2
        fi
    done
done
for unit in "$root"/deployment/redhat/systemd/*.service; do
    target="/etc/systemd/system/$(basename -- "$unit")"
    if [[ -e "$target" || -L "$target" ]]; then
        if [[ -L "$target" || ! -f "$target" ]] || ! grep -qx '# Managed by elv Red Hat hosting' "$target"; then
            echo "Refusing to replace an unowned service unit: $target" >&2
            exit 2
        fi
    fi
done
for unit in "$root"/deployment/redhat/systemd/*.service; do
    install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$(basename -- "$unit")"
done
systemd-analyze verify /etc/systemd/system/elv-poc001-agent.service /etc/systemd/system/elv-poc001-ui.service /etc/systemd/system/elv-poc002-ui.service
systemctl daemon-reload
echo "Units installed, not started. Complete /etc/elv/*.env and permissions using the runbook."