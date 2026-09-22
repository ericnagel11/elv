#!/usr/bin/env python3
"""Systemd entrypoint: validate nonsecret VM settings and exec a private service."""

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID

POCS = {"001": "001-config-driven-responses", "002": "002-regional-multilingual-experience"}


def uses_log_analytics(poc):
    """PoC002 stays legacy; only explicit opt-in enables LA for PoC001.

    Do not validate Blob settings here. History configuration/writer failures
    belong to PoC001's best-effort warning boundary, not service startup.
    """
    return poc == "002" or os.environ.get("ELV_AUDIT_BACKEND", "blob").strip().lower() == "loganalytics"


def command_for(poc, component, python, project):
    if poc not in POCS:
        raise ValueError("Unknown PoC.")
    if component == "agent" and poc == "001":
        return [python, "-m", "uvicorn", "a2a_server:app", "--host", "127.0.0.1", "--port", "9999"]
    if component != "ui":
        raise ValueError("Only PoC 001 has a separate agent.")
    return [
        python, "-m", "streamlit", "run", str(project / "app.py"),
        "--server.address=127.0.0.1", f"--server.port={'8501' if poc == '001' else '8502'}",
        "--server.headless=true", "--server.enableCORS=true",
        "--server.enableXsrfProtection=true", "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]


def validate_settings(poc):
    # Only configuration-key names appear in errors, never their values.
    endpoint_keys = [
        "AZURE_APPCONFIG_ENDPOINT", "AZURE_APPCONFIG_DRAFT_ENDPOINT",
        "AZURE_OPENAI_ENDPOINT", "AZURE_SEARCH_ENDPOINT",
    ]
    if poc == "002":
        endpoint_keys.append("AZURE_LANGUAGE_ENDPOINT")
    for key in endpoint_keys:
        value = os.environ.get(key, "")
        try:
            url = urlsplit(value)
            valid = (url.scheme == "https" and url.hostname and not url.username
                     and not url.password and not url.query and not url.fragment
                     and url.path in {"", "/"} and url.port in {None, 443}
                     and not any(char in value for char in "<> \t\r\n"))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"{key} must contain an HTTPS service endpoint, without credentials or a path.")
    if os.environ["AZURE_APPCONFIG_ENDPOINT"].lower().rstrip("/") == os.environ["AZURE_APPCONFIG_DRAFT_ENDPOINT"].lower().rstrip("/"):
        raise ValueError("Live and draft endpoints must be different stores.")
    uuid_keys = ["AZURE_TENANT_ID"]
    if uses_log_analytics(poc):
        uuid_keys.append("AZURE_LOG_ANALYTICS_WORKSPACE_ID")
    for key in uuid_keys:
        try:
            if not UUID(os.environ.get(key, "")).int:
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} must contain a nonzero UUID.") from None
    for key in ("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION"):
        value = os.environ.get(key, "").strip()
        if not value or any(char in value for char in "<>\r\n"):
            raise ValueError(f"{key} must be configured for the existing model deployment.")
    for key in ("AZURE_CLIENT_SECRET", "AZURE_CLIENT_CERTIFICATE_PATH", "AZURE_FEDERATED_TOKEN_FILE"):
        if os.environ.get(key):
            raise ValueError(f"Remove {key}; these services use managed identities only.")
    state = Path(os.environ.get("ELV_STATE_DIRECTORY", ""))
    if not state.is_absolute() or not state.is_dir() or not os.access(state, os.W_OK):
        raise ValueError("ELV_STATE_DIRECTORY must be an existing, writable absolute state directory.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poc", required=True, choices=POCS)
    parser.add_argument("--component", required=True, choices=("ui", "agent"))
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("Run only on the approved Linux VM as a non-root service user.")
    root = Path(__file__).resolve().parents[2]
    project = root / "pocs" / POCS[args.poc]
    command = command_for(args.poc, args.component, sys.executable, project)
    # Set in the process, not only in the unit: EnvironmentFile cannot turn off
    # the VM credential policy or redirect the agent to a public listener.
    os.environ["ELV_HOSTING_MODE"] = "azure-vm"
    os.environ["A2A_AGENT_URL"] = "http://127.0.0.1:9999"
    os.environ["A2A_AGENT_HOST"] = "127.0.0.1"
    os.environ["A2A_AGENT_PORT"] = "9999"
    validate_settings(args.poc)
    sys.path.insert(0, str(project))
    import hosting
    import rbac
    hosting.identity_ids(rbac.PERSONAS)
    if uses_log_analytics(args.poc):
        hosting.audit_resource_ids()
    os.chdir(project)
    os.execv(sys.executable, command)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"VM configuration error: {error}", file=sys.stderr)
        sys.exit(2)