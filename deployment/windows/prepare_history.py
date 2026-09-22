"""Preview or create the private history container and enable the local VM setting."""

import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

from azure.core.exceptions import (
    AzureError, ClientAuthenticationError, HttpResponseError,
    ResourceExistsError, ResourceNotFoundError,
)
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import ContainerClient, ExponentialRetry

from run import PROJECT, load_settings, process_environment, validate_settings


REQUEST_TIMEOUT = 15


class HistorySetupError(RuntimeError):
    """A safe setup diagnostic that contains no provider response or credentials."""


def ensure_private_container(client) -> bool:
    """Create only when missing; never change an existing container's access policy."""
    created = False
    try:
        properties = client.get_container_properties(timeout=REQUEST_TIMEOUT)
    except ResourceNotFoundError:
        try:
            client.create_container(public_access=None, timeout=REQUEST_TIMEOUT)
            created = True
        except ResourceExistsError:
            pass
        properties = client.get_container_properties(timeout=REQUEST_TIMEOUT)
    if properties.public_access is not None:
        raise HistorySetupError(
            "The history container permits anonymous access. Local settings were not changed; "
            "ask its owner to review the target. Its access policy was not modified."
        )
    return created


def _replace_config(path: Path, replacement: Path) -> None:
    """Use Windows replacement semantics to preserve the destination file's DACL."""
    replace_file = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace_file.argtypes = (
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
    )
    replace_file.restype = wintypes.BOOL
    if not replace_file(str(path), str(replacement), None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def enable_history(path: Path, original: bytes, settings: dict) -> bool:
    """Replace validated local JSON only after Storage preparation has succeeded."""
    if path.read_bytes() != original:
        raise HistorySetupError("Runtime JSON changed during setup. It was not overwritten; preview again.")
    if settings.get("ELV_ENABLE_CONFIG_HISTORY") == "true":
        return False
    enabled = {**settings, "ELV_ENABLE_CONFIG_HISTORY": "true"}
    validate_settings(enabled)
    payload = (json.dumps(enabled, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    replacement = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".elv-history-", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            replacement = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != original:
            raise HistorySetupError("Runtime JSON changed during setup. It was not overwritten; preview again.")
        _replace_config(path, replacement)
    finally:
        if replacement is not None:
            replacement.unlink(missing_ok=True)
    if load_settings(path) != enabled:
        raise HistorySetupError("Runtime JSON readback did not match. Inspect it before restarting the UI.")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-azure-host", action="store_true")
    args = parser.parse_args(argv)
    if args.apply:
        if sys.platform != "win32" or not args.approved_azure_host:
            raise ValueError("Applying requires the approved Azure Windows VM and --approved-azure-host.")
        python = PROJECT / ".venv" / "Scripts" / "python.exe"
        if Path(sys.executable).resolve() != python.resolve():
            raise ValueError("Use PoC 001's .venv/Scripts/python.exe to apply history setup.")
    path = args.config.resolve()
    original = path.read_bytes()
    settings = load_settings(path)
    if path.read_bytes() != original:
        raise HistorySetupError("Runtime JSON changed while reading it. Preview again before applying.")
    enabled = {**settings, "ELV_ENABLE_CONFIG_HISTORY": "true"}
    validate_settings(enabled)
    print(f"Storage account: {enabled['ELV_AUDIT_BLOB_ACCOUNT_URL']}")
    print(f"Private history container: {enabled['ELV_AUDIT_BLOB_CONTAINER']}")
    print("Local runtime setting: ELV_ENABLE_CONFIG_HISTORY=true")
    if not args.apply:
        print("PREVIEW_ONLY: no credentials, Azure calls or local file changes. Use --apply --approved-azure-host after approval.")
        return 0

    os.environ.update(process_environment(enabled))
    logging.getLogger("azure").setLevel(logging.CRITICAL)
    with ManagedIdentityCredential(client_id=enabled["ELV_MI_APP_CLIENT_ID"].strip()) as credential:
        with ContainerClient(
            account_url=enabled["ELV_AUDIT_BLOB_ACCOUNT_URL"],
            container_name=enabled["ELV_AUDIT_BLOB_CONTAINER"], credential=credential,
            connection_timeout=5, read_timeout=REQUEST_TIMEOUT,
            retry_policy=ExponentialRetry(retry_total=0),
        ) as client:
            created = ensure_private_container(client)
    print("CONTAINER_CREATED_PRIVATE" if created else "CONTAINER_ALREADY_PRIVATE")
    changed = enable_history(path, original, settings)
    print("HISTORY_ENABLED" if changed else "HISTORY_ALREADY_ENABLED")
    print("Restart the PoC UI to load this setting. No history event was uploaded; test the first save/readback separately.")
    return 0


def cli(argv=None) -> int:
    try:
        return main(argv)
    except ValueError as error:
        print(f"HISTORY_SETUP_INPUT_ERROR: {error}", file=sys.stderr)
        return 2
    except HistorySetupError as error:
        print(f"HISTORY_SETUP_STOPPED: {error}", file=sys.stderr)
    except ClientAuthenticationError:
        print("HISTORY_SETUP_AUTH_FAILED: verify managed identity Client ID and VM attachment.", file=sys.stderr)
        return 3
    except HttpResponseError as error:
        status = error.status_code if isinstance(error.status_code, int) else "UNKNOWN"
        print(f"HISTORY_SETUP_FAILED: HTTP {status}; verify container read/create access and network policy. No permissions were changed.", file=sys.stderr)
    except AzureError:
        print("HISTORY_SETUP_FAILED: verify identity, private routing, proxy and CA trust. No raw provider details printed.", file=sys.stderr)
    except OSError:
        print("HISTORY_SETUP_LOCAL_ERROR: check runtime file/directory access and whether another process holds the file.", file=sys.stderr)
        print("The private container may already exist. Inspect runtime JSON before retrying; no rollback is attempted.", file=sys.stderr)
        return 5
    print("A container created before failure may remain. No deletion, role change, or automatic retry was attempted.", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(cli())