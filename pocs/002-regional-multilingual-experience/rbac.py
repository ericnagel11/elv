"""Persona and credential definitions for the RBAC governance demonstration.

Five Microsoft Entra service principals hold Azure built-in roles across two App
Configuration stores. Every allow and every denial in this application is
enforced by Azure RBAC, not by application-side checks.

The market owner is the persona that makes the honest point. The role an
organization actually wants is "may change only the de-DE market", and Azure
cannot express it: role assignment conditions are available for blob storage and
queue storage data actions, not for App Configuration, so a data-plane role
cannot be narrowed to a label. The market owner therefore holds exactly the same
Azure permissions as the global experience designer. Restricting them to their
own market requires a compensating control outside Azure RBAC, and the
governance tab names it rather than implying the platform does it.

Secrets are read from roles.local.json, which scripts/setup-governance.ps1
writes and .gitignore excludes. Using client secrets is a proof-of-concept
shortcut so that one process can act as several identities; a production system
would use managed identity or sign the user in directly.
"""

import json
import os
from functools import lru_cache

from azure.identity import ClientSecretCredential, DefaultAzureCredential

ROLES_FILE = os.path.join(os.path.dirname(__file__), "roles.local.json")

READER = "App Configuration Data Reader"
OWNER = "App Configuration Data Owner"

# Ordered so the UI presents least privilege to most privilege.
PERSONAS = {
    "viewer": {
        "label": "Viewer / Auditor",
        "summary": "Reviews configuration and the audit trail. Changes nothing.",
        "roles": {"production": READER, "draft": READER},
        "scope_note": "",
    },
    "designer": {
        "label": "Global experience designer",
        "summary": "Owns the baseline layer that every market inherits from.",
        "roles": {"production": READER, "draft": OWNER},
        "scope_note": "",
    },
    "market_owner": {
        "label": "Market owner (de-DE)",
        "summary": "Owns the German market's register, terminology, and content scope.",
        "roles": {"production": READER, "draft": OWNER},
        "scope_note": (
            "Azure grants this identity the same permissions as the global designer. "
            "It can edit every market's layer, not only de-DE, because App Configuration "
            "does not support role assignment conditions and a data-plane role cannot be "
            "scoped to a label. Per-market delegation needs a compensating control."
        ),
    },
    "approver": {
        "label": "Release approver",
        "summary": "Reviews a proposed layer and publishes it to production.",
        "roles": {"production": OWNER, "draft": OWNER},
        "scope_note": "",
    },
    "app": {
        "label": "Application runtime",
        "summary": "Least privilege. Reads the live configuration and nothing else.",
        "roles": {"production": READER},
        "scope_note": "",
    },
}

DEFAULT_PERSONA = "market_owner"

# The controls that deliver what Azure RBAC cannot. Shown in the UI beside the
# limitation so the gap and its remedy are never separated.
COMPENSATING_CONTROLS = [
    {
        "control": "Per-locale code ownership",
        "delivers": "A named reviewer per market for prompt assets, glossaries, and notices",
        "cost": "Market assets must live in a repository and be written by a pipeline identity",
    },
    {
        "control": "Gatekeeper API or Logic App",
        "delivers": "Rules RBAC cannot express, such as 'this team may change only experience:tone for de-DE'",
        "cost": "A trusted component you own, secure, audit, and keep available",
    },
    {
        "control": "A store per market cohort",
        "delivers": "Real isolation enforced by Azure",
        "cost": "Store counts multiply, and tier limits become governance constraints",
    },
    {
        "control": "Privileged Identity Management",
        "delivers": "Time-bound approver access requiring activation with justification",
        "cost": "Entra ID P2 licensing and an activation process",
    },
]


@lru_cache(maxsize=1)
def _roles_file() -> dict:
    if not os.path.exists(ROLES_FILE):
        return {}
    with open(ROLES_FILE, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def personas_configured() -> bool:
    """True once setup-governance.ps1 has provisioned the service principals."""
    return bool(_roles_file().get("personas"))


def credential_for(persona: str):
    """Return the credential for a persona.

    Falls back to DefaultAzureCredential (the signed-in developer) when the
    roles file is absent, so the application still runs before the governance
    layer is provisioned.
    """
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
    entry = (_roles_file().get("personas") or {}).get(persona) or {}
    return entry.get("displayName", "not provisioned (using your sign-in)")


def credential_warnings() -> list:
    """Report personas that share one app registration.

    Two personas pointing at the same registration means only one of them holds
    a valid secret, because issuing a secret replaces the previous one. The
    other persona then fails to sign in, which is easily mistaken for an RBAC
    denial.
    """
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
