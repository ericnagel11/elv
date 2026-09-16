"""Persona and credential definitions for the RBAC governance demonstration.

Four Microsoft Entra service principals hold different Azure built-in roles
across two App Configuration stores. Every allow and every denial in this
application is enforced by Azure RBAC, not by application-side checks.

Azure VM mode uses explicitly selected managed identities and never reads local
secrets. Legacy development mode reads roles.local.json, which the original
setup script writes and .gitignore excludes. Neither mode turns the persona
selector into user authentication or isolates identities between VM processes.
"""

import json
import os
from functools import lru_cache

from azure.identity import ClientSecretCredential, DefaultAzureCredential

import hosting

ROLES_FILE = os.path.join(os.path.dirname(__file__), "roles.local.json")

READER = "App Configuration Data Reader"
OWNER = "App Configuration Data Owner"

# Ordered so the UI presents least privilege to most privilege.
PERSONAS = {
    "viewer": {
        "label": "Viewer / Auditor",
        "summary": "Reviews the experience and the audit trail. Changes nothing.",
        "roles": {"production": READER, "draft": READER},
    },
    "designer": {
        "label": "Experience designer",
        "summary": "Owns the draft experience. Cannot publish to production.",
        "roles": {"production": READER, "draft": OWNER},
    },
    "approver": {
        "label": "Release approver",
        "summary": "Reviews the draft and publishes it to production.",
        "roles": {"production": OWNER, "draft": OWNER},
    },
    "app": {
        "label": "Application runtime",
        "summary": "Least privilege. Reads the live experience and nothing else.",
        "roles": {"production": READER},
    },
}

DEFAULT_PERSONA = "designer"


@lru_cache(maxsize=1)
def _roles_file() -> dict:
    if not os.path.exists(ROLES_FILE):
        return {}
    with open(ROLES_FILE, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def personas_configured() -> bool:
    """Validate local identity configuration; this does not verify Azure roles."""
    if hosting.vm_mode():
        hosting.identity_ids(PERSONAS)
        return True
    return bool(_roles_file().get("personas"))


def credential_for(persona: str):
    """Return the credential for a persona.

    VM mode never falls back. Only legacy development mode uses the signed-in
    developer when the roles file is absent.
    """
    if hosting.vm_mode():
        return hosting.managed_credential(persona, PERSONAS)
    data = _roles_file()
    entry = (data.get("personas") or {}).get(persona)
    if not entry:
        return DefaultAzureCredential()
    return ClientSecretCredential(
        tenant_id=data["tenantId"],
        client_id=entry["clientId"],
        client_secret=entry["clientSecret"],
    )


def display_name(persona: str) -> str:
    if hosting.vm_mode():
        return f"Managed identity ({persona})"
    entry = (_roles_file().get("personas") or {}).get(persona) or {}
    return entry.get("displayName", "not provisioned (using your sign-in)")


def service_credential(service: str):
    """Runtime and audit never borrow a developer credential in VM mode."""
    if service not in {"runtime", "audit"}:
        raise ValueError("Unknown service identity.")
    if hosting.vm_mode():
        return hosting.managed_credential("app" if service == "runtime" else "audit", PERSONAS)
    return DefaultAzureCredential()


def credential_warnings() -> list:
    """Report personas that share one app registration.

    Two personas pointing at the same registration means only one of them holds
    a valid secret, because issuing a secret replaces the previous one. The
    other persona then fails to sign in, which is easily mistaken for an RBAC
    denial.
    """
    if hosting.vm_mode():
        hosting.identity_ids(PERSONAS)
        return []
    personas = _roles_file().get("personas") or {}
    warnings = []
    seen = {}
    for key, entry in personas.items():
        client_id = entry.get("clientId")
        if not client_id:
            continue
        if client_id in seen:
            warnings.append(
                f"'{key}' and '{seen[client_id]}' share the app registration "
                f"{entry.get('displayName')}. Only one can sign in. "
                "Re-run scripts/setup-governance.ps1."
            )
        else:
            seen[client_id] = key
    return warnings


def role_rows(persona: str) -> list:
    """Role assignments held by a persona, for display in the UI."""
    roles = PERSONAS[persona]["roles"]
    rows = []
    for store in ("production", "draft"):
        rows.append({
            "scope": f"{store} store",
            "role": roles.get(store, "no role assigned"),
        })
    return rows
