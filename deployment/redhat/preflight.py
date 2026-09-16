#!/usr/bin/env python3
"""Read-only host inventory. No Azure calls, token requests or PoC imports."""

import argparse
import json
from pathlib import Path
import platform
import shutil
import socket
import sys


def read_release(path=Path("/etc/os-release")):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"').strip("'")
    return values


def checks():
    results = []

    def add(name, status, detail):
        results.append({"check": name, "status": status, "detail": detail})

    release = read_release()
    supported = release.get("ID") == "rhel" and release.get("VERSION_ID", "").split(".")[0] in {"8", "9", "10"}
    add("RHEL", "PASS" if supported else "FAIL", release.get("PRETTY_NAME", platform.system()))
    add("Architecture", "PASS" if platform.machine() == "x86_64" else "WARN",
        platform.machine() + "; non-x86_64 requires package/wheel validation")
    add("Python", "PASS" if sys.version_info >= (3, 10) else "FAIL",
        platform.python_version() + "; minimum 3.10, prefer approved 3.11/3.12")
    add("systemd", "PASS" if shutil.which("systemctl") and Path("/run/systemd/system").is_dir() else "FAIL",
        "Requires systemd as the VM service manager")
    for name in ("git", "bash", "curl"):
        add(name, "PASS" if shutil.which(name) else "FAIL", "Host deployment/diagnostic tool")
    for name in ("az", "pwsh"):
        add(name, "PASS" if shutil.which(name) else "WARN",
            "Optional Azure setup tool; not required by running Python services")
    try:
        import ensurepip  # noqa: F401
        import ssl
        import venv  # noqa: F401
        add("Python venv/TLS", "PASS", ssl.OPENSSL_VERSION)
    except ImportError:
        add("Python venv/TLS", "FAIL", "Install approved Python venv/pip/TLS support")
    free_gib = shutil.disk_usage(Path(__file__).resolve().parent).free / (1024 ** 3)
    add("Free disk", "PASS" if free_gib >= 5 else "WARN",
        "{:.1f} GiB available; 5 GiB is a planning allowance, not a measured requirement".format(free_gib))
    for name, path in (("SELinux enforcing", "/sys/fs/selinux/enforce"), ("FIPS enabled", "/proc/sys/crypto/fips_enabled")):
        try:
            value = Path(path).read_text(encoding="ascii").strip()
        except OSError:
            value = "not readable"
        add(name, "INFO", value + "; retain organizational policy, validate compatible packages")
    for port in (8501, 8502, 9999):
        with socket.socket() as connection:
            connection.settimeout(0.5)
            in_use = connection.connect_ex(("127.0.0.1", port)) == 0
        add("Port " + str(port), "WARN" if in_use else "PASS",
            "Already listening; verify it is the intended service" if in_use else "No loopback listener detected")
    add("External readiness", "WARN",
        "Not tested: installation rights, package sources, tenant, Azure roles, DNS/HTTPS, IMDS and approved SSH route")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print nonsecret host results as JSON")
    args = parser.parse_args()
    results = checks()
    if args.json:
        print(json.dumps({"checks": results, "azure_validated": False}, indent=2))
    else:
        for result in results:
            print("[{status}] {check}: {detail}".format(**result))
    return 1 if any(result["status"] == "FAIL" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())