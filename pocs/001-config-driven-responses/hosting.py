"""Hosting policy, kept identical in both independently runnable PoCs.

Azure VM mode uses only explicit managed identities. No token is requested by
validation. A VM is one trust boundary: separate identities do not isolate its
processes or users. See deployment/redhat/README.md before attaching identities.
"""

import os
from pathlib import Path
import re
from uuid import UUID

from azure.identity import ManagedIdentityCredential
from dotenv import load_dotenv


def vm_mode() -> bool:
    mode = os.environ.get("ELV_HOSTING_MODE", "development")
    if mode not in {"development", "azure-vm"}:
        raise ValueError("ELV_HOSTING_MODE must be development or azure-vm.")
    return mode == "azure-vm"


def load_environment() -> None:
    """Never discover dotenv files on the VM or overwrite process settings."""
    if not vm_mode():
        load_dotenv(
            dotenv_path=Path(__file__).with_name(".env"),
            encoding="utf-8-sig",
            override=False,
        )


def identity_ids(personas) -> dict:
    """Validate a complete, distinct persona/audit map without exposing values."""
    result = {}
    for name in [*personas, "audit"]:
        key = f"ELV_MI_{name.upper()}_CLIENT_ID"
        value = os.environ.get(key, "").strip()
        try:
            identity = UUID(value)
            if not identity.int:
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} must contain a nonzero managed identity client UUID.") from None
        normalized = str(identity)
        if normalized in result.values():
            raise ValueError(f"{key} must not reuse another persona or audit identity.")
        result[name] = normalized
    return result


def managed_credential(name: str, personas) -> ManagedIdentityCredential:
    identities = identity_ids(personas)
    if name not in identities:
        raise ValueError("An explicit, configured persona or service identity is required.")
    return ManagedIdentityCredential(client_id=identities[name])


def audit_resource_ids() -> tuple:
    """Allow resource-context queries only for the declared two-store boundary."""
    resources = []
    pattern = re.compile(
        r"/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/"
        r"Microsoft\.AppConfiguration/configurationStores/[a-z0-9-]+",
        re.IGNORECASE,
    )
    for key in ("AZURE_APPCONFIG_RESOURCE_ID", "AZURE_APPCONFIG_DRAFT_RESOURCE_ID"):
        value = os.environ.get(key, "").strip().rstrip("/")
        if not pattern.fullmatch(value):
            raise ValueError(f"{key} must be an App Configuration ARM resource ID.")
        try:
            UUID(value.split("/")[2])
        except ValueError:
            raise ValueError(f"{key} has an invalid subscription ID.") from None
        if value.lower() in {resource.lower() for resource in resources}:
            raise ValueError("Live and draft App Configuration resources must be distinct.")
        resources.append(value)
    return tuple(resources)