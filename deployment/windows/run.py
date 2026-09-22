"""Launch a localhost-only PoC 001 comparison on approved Azure Windows compute."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import UUID


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "pocs" / "001-config-driven-responses"
REQUIRED_SETTINGS = frozenset({
    "AZURE_APPCONFIG_ENDPOINT", "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION",
    "ELV_MI_APP_CLIENT_ID", "ELV_STATE_DIRECTORY",
})
ALLOWED_SETTINGS = REQUIRED_SETTINGS | {
    "ELV_OPENAI_REQUEST_PROFILE", "ELV_ENABLE_CONFIG_EDITING", "ELV_ENABLE_RAG",
    "AZURE_SEARCH_ENDPOINT", "ELV_SEARCH_ALLOWED_INDEXES",
    "ELV_ENABLE_CONFIG_HISTORY", "ELV_AUDIT_BLOB_ACCOUNT_URL", "ELV_AUDIT_BLOB_CONTAINER",
}
FORCED_SETTINGS = {
    "ELV_HOSTING_MODE": "azure-vm",
    "ELV_DEMO_MODE": "comparison",
    "ELV_OPENAI_REQUEST_PROFILE": "gpt4o",
    "A2A_AGENT_URL": "http://127.0.0.1:9999",
    "A2A_AGENT_HOST": "127.0.0.1",
    "A2A_AGENT_PORT": "9999",
}


def _unique_settings(pairs):
    settings = {}
    for key, value in pairs:
        if key in settings:
            raise ValueError("Runtime JSON must not contain duplicate setting names.")
        settings[key] = value
    return settings


def load_settings(path: Path) -> dict:
    path = path.resolve()
    if path.is_relative_to(ROOT) or path.suffix.lower() != ".json":
        raise ValueError("Use an explicit runtime JSON file outside the source checkout.")
    try:
        with path.open(encoding="utf-8-sig") as handle:
            settings = json.load(handle, object_pairs_hook=_unique_settings)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Cannot read runtime JSON; check its path, permissions and syntax.") from None
    validate_settings(settings)
    return settings


def validate_settings(settings: dict) -> None:
    if not isinstance(settings, dict) or set(settings) - ALLOWED_SETTINGS:
        raise ValueError("Runtime JSON must contain only the documented nonsecret setting names.")
    for key in sorted(REQUIRED_SETTINGS):
        if not isinstance(settings.get(key), str) or not settings[key].strip():
            raise ValueError(f"{key} must be a nonempty string in runtime JSON.")
    for key, value in settings.items():
        if not isinstance(value, str) or any(ord(character) < 32 for character in value):
            raise ValueError(f"{key} must be a string without control characters.")
    endpoint_keys = ["AZURE_APPCONFIG_ENDPOINT", "AZURE_OPENAI_ENDPOINT"]
    if settings.get("ELV_ENABLE_RAG", "false") not in {"true", "false"}:
        raise ValueError("ELV_ENABLE_RAG must be true or false.")
    if settings.get("ELV_ENABLE_RAG") == "true":
        if not settings.get("AZURE_SEARCH_ENDPOINT"):
            raise ValueError("AZURE_SEARCH_ENDPOINT is required when RAG is enabled.")
        indexes = settings.get("ELV_SEARCH_ALLOWED_INDEXES", "").split(",")
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,127}", name.strip()) for name in indexes):
            raise ValueError("ELV_SEARCH_ALLOWED_INDEXES must name the approved indexes when RAG is enabled.")
    if settings.get("AZURE_SEARCH_ENDPOINT"):
        endpoint_keys.append("AZURE_SEARCH_ENDPOINT")
    for key in endpoint_keys:
        value = settings[key]
        try:
            url = urlsplit(value)
            valid = (url.scheme == "https" and url.hostname and not url.username
                     and not url.password and not url.query and not url.fragment
                     and url.path in {"", "/"} and url.port in {None, 443}
                     and not any(character in value for character in "<> \\\t\r\n"))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"{key} must be an HTTPS service endpoint without credentials or a path.")
    if not re.fullmatch(r"[\w.-]+", settings["AZURE_OPENAI_DEPLOYMENT"], flags=re.ASCII):
        raise ValueError("AZURE_OPENAI_DEPLOYMENT must name an existing deployment.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", settings["AZURE_OPENAI_API_VERSION"]):
        raise ValueError("AZURE_OPENAI_API_VERSION must be an approved GA API date.")
    try:
        if not UUID(settings["ELV_MI_APP_CLIENT_ID"].strip()).int:
            raise ValueError
    except ValueError:
        raise ValueError("ELV_MI_APP_CLIENT_ID must be a nonzero managed identity client UUID.") from None
    if settings.get("ELV_OPENAI_REQUEST_PROFILE", "gpt4o") != "gpt4o":
        raise ValueError("This launcher requires ELV_OPENAI_REQUEST_PROFILE=gpt4o.")
    if settings.get("ELV_ENABLE_CONFIG_EDITING", "false") not in {"true", "false"}:
        raise ValueError("ELV_ENABLE_CONFIG_EDITING must be true or false.")
    if settings.get("ELV_ENABLE_CONFIG_HISTORY", "false") not in {"true", "false"}:
        raise ValueError("ELV_ENABLE_CONFIG_HISTORY must be true or false.")
    history_enabled = settings.get("ELV_ENABLE_CONFIG_HISTORY") == "true"
    blob_account = settings.get("ELV_AUDIT_BLOB_ACCOUNT_URL", "")
    blob_container = settings.get("ELV_AUDIT_BLOB_CONTAINER", "")
    if (history_enabled or "ELV_AUDIT_BLOB_ACCOUNT_URL" in settings) and not re.fullmatch(
        r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/?", blob_account
    ):
        raise ValueError("ELV_AUDIT_BLOB_ACCOUNT_URL must be a standard HTTPS Blob endpoint without credentials or a path.")
    if (history_enabled or "ELV_AUDIT_BLOB_CONTAINER" in settings) and not re.fullmatch(
        r"(?=.{3,63}\Z)[a-z0-9]+(?:-[a-z0-9]+)*", blob_container
    ):
        raise ValueError("ELV_AUDIT_BLOB_CONTAINER must name the approved private history container.")
    state = Path(settings["ELV_STATE_DIRECTORY"])
    if (not state.is_absolute() or state.resolve().is_relative_to(ROOT)
            or not state.is_dir() or not os.access(state, os.W_OK)):
        raise ValueError("ELV_STATE_DIRECTORY must be an existing writable absolute directory outside the checkout.")


def process_environment(settings: dict) -> dict:
    validate_settings(settings)
    environment = os.environ.copy()
    for key in ("AZURE_CLIENT_SECRET", "AZURE_CLIENT_CERTIFICATE_PATH", "AZURE_FEDERATED_TOKEN_FILE"):
        if environment.get(key):
            raise ValueError(f"Remove {key}; this launcher uses managed identity only.")
    environment.update(settings)
    environment.update(FORCED_SETTINGS)
    environment["ELV_ENABLE_CONFIG_EDITING"] = settings.get("ELV_ENABLE_CONFIG_EDITING", "false")
    environment["ELV_ENABLE_RAG"] = settings.get("ELV_ENABLE_RAG", "false")
    environment["AZURE_SEARCH_ENDPOINT"] = settings.get("AZURE_SEARCH_ENDPOINT", "")
    environment["ELV_SEARCH_ALLOWED_INDEXES"] = settings.get("ELV_SEARCH_ALLOWED_INDEXES", "")
    environment["ELV_ENABLE_CONFIG_HISTORY"] = settings.get("ELV_ENABLE_CONFIG_HISTORY", "false")
    environment["ELV_AUDIT_BACKEND"] = "blob"
    environment["ELV_AUDIT_BLOB_ACCOUNT_URL"] = settings.get("ELV_AUDIT_BLOB_ACCOUNT_URL", "")
    environment["ELV_AUDIT_BLOB_CONTAINER"] = settings.get("ELV_AUDIT_BLOB_CONTAINER", "")
    bypasses = []
    for key in ("NO_PROXY", "no_proxy"):
        bypasses.extend(value.strip() for value in environment.get(key, "").split(",") if value.strip())
    bypasses.extend(("169.254.169.254", "127.0.0.1", "localhost"))
    bypass = ",".join(dict.fromkeys(bypasses))
    environment.update({"NO_PROXY": bypass, "no_proxy": bypass})
    return environment


def command_for(component: str, python: str, project: Path) -> list:
    if component == "agent":
        return [python, "-m", "uvicorn", "a2a_server:app", "--host", "127.0.0.1", "--port", "9999"]
    if component == "ui":
        return [
            python, "-m", "streamlit", "run", str(project / "app.py"),
            "--server.address=127.0.0.1", "--server.port=8501",
            "--server.headless=true", "--server.enableCORS=true",
            "--server.enableXsrfProtection=true", "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ]
    raise ValueError("Component must be agent or ui.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--component", choices=("agent", "ui"), required=True)
    parser.add_argument("--approved-azure-host", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or not args.approved_azure_host:
        raise ValueError("Run on the approved Azure Windows VM with --approved-azure-host.")
    python = PROJECT / ".venv" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != python.resolve():
        raise ValueError("Run this launcher with PoC 001's .venv/Scripts/python.exe.")
    settings = load_settings(args.config)
    environment = process_environment(settings)
    os.environ.update(environment)
    sys.path.insert(0, str(PROJECT))
    import rbac
    rbac.comparison_mode()
    rbac.runtime_identity_id()
    rbac.config_editing_enabled()
    rbac.config_history_enabled()
    if rbac.rag_enabled():
        rbac.approved_search_indexes()
    if args.validate_only:
        print("CONFIGURATION_VALID: no token requests or Azure calls were made.")
        return 0
    command = command_for(args.component, str(python), PROJECT)
    try:
        return subprocess.run(command, cwd=PROJECT, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(f"Windows configuration error: {error}", file=sys.stderr)
        sys.exit(2)
    except OSError:
        print("Cannot launch the component; check interpreter, directory and file permissions.", file=sys.stderr)
        sys.exit(2)