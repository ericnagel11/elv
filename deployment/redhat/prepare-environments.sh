#!/usr/bin/env bash
# Run on the VM as the trusted checkout owner, NOT root or an application user.
set -euo pipefail
# Dependencies/source contain no secrets and must be readable by service users.
# Private credentials remain outside the checkout and are never copied here.
umask 022

if [[ $# -ne 1 || "$1" != /* ]]; then
    echo "Usage: bash deployment/redhat/prepare-environments.sh /absolute/path/to/python3.12" >&2
    exit 2
fi
if [[ $(uname -s) != Linux || $EUID -eq 0 ]]; then
    echo "Run on the approved Linux VM as the non-root deployment operator." >&2
    exit 2
fi
python="$1"
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
"$python" "$root/deployment/redhat/preflight.py"

for poc in 001-config-driven-responses 002-regional-multilingual-experience; do
    project="$root/pocs/$poc"
    venv="$project/.venv"
    [[ -w "$project" ]] || { echo "Deployment operator cannot write $poc." >&2; exit 2; }
    if [[ -L "$venv" || ( -e "$venv" && ! -f "$venv/pyvenv.cfg" ) ]]; then
        echo "Refusing an unexpected .venv entry in $poc." >&2
        exit 2
    fi
    if [[ ! -d "$venv" ]]; then
        "$python" -m venv "$venv"
    fi
    "$venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
    # Honor the organization's pip configuration/mirror. Never embed credentials
    # in arguments, bypass TLS checks, or install packages into system Python.
    "$venv/bin/python" -m pip install --requirement "$project/requirements.txt"
    "$venv/bin/python" -m pip check
    "$venv/bin/python" -m pip freeze > "$project/.installed-requirements.txt"
done
echo "Environments prepared. No apps started or Azure resources changed. Run the remote tests next."