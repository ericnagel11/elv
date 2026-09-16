"""Run on the VM in each PoC venv. No Azure requests or credentials required."""

import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
POCS = (
    ROOT / "pocs/001-config-driven-responses",
    ROOT / "pocs/002-regional-multilingual-experience",
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity_env(personas):
    names = [*personas, "audit"]
    return {
        "ELV_HOSTING_MODE": "azure-vm",
        **{
            f"ELV_MI_{name.upper()}_CLIENT_ID": f"00000000-0000-4000-8000-{i:012d}"
            for i, name in enumerate(names, start=1)
        },
    }


class HostingContracts(unittest.TestCase):
    def test_helpers_remain_identical_for_standalone_pocs(self):
        self.assertEqual(
            (POCS[0] / "hosting.py").read_bytes(),
            (POCS[1] / "hosting.py").read_bytes(),
        )

    def test_vm_never_loads_dotenv(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with self.subTest(poc=poc.name), patch.dict(
                os.environ, {"ELV_HOSTING_MODE": "azure-vm"}, clear=True
            ), patch.object(host, "load_dotenv") as loader:
                host.load_environment()
                loader.assert_not_called()

    def test_development_dotenv_cannot_override_process_settings(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with self.subTest(poc=poc.name), patch.dict(os.environ, {}, clear=True), \
                    patch.object(host, "load_dotenv") as loader:
                host.load_environment()
                self.assertFalse(loader.call_args.kwargs["override"])
                self.assertEqual(loader.call_args.kwargs["dotenv_path"], poc / ".env")

    def test_invalid_mode_fails_closed(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with self.subTest(poc=poc.name), patch.dict(
                os.environ, {"ELV_HOSTING_MODE": "typo"}, clear=True
            ):
                with self.assertRaises(ValueError):
                    host.vm_mode()

    def test_personas_use_explicit_distinct_identities_not_legacy_secrets(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with patch.dict(sys.modules, {"hosting": host}):
                rbac = load_module("test_rbac", poc / "rbac.py")
            env = identity_env(rbac.PERSONAS)
            with self.subTest(poc=poc.name), patch.dict(os.environ, env, clear=True), \
                    patch.object(host, "ManagedIdentityCredential") as credential, \
                    patch.object(rbac, "_roles_file", side_effect=AssertionError("legacy file")), \
                    patch.object(rbac, "DefaultAzureCredential", side_effect=AssertionError("fallback")):
                self.assertTrue(rbac.personas_configured())
                self.assertEqual(rbac.credential_warnings(), [])
                for persona in rbac.PERSONAS:
                    rbac.credential_for(persona)
                    credential.assert_called_with(
                        client_id=env[f"ELV_MI_{persona.upper()}_CLIENT_ID"]
                    )
                    self.assertIn("Managed identity", rbac.display_name(persona))
                rbac.service_credential("runtime")
                credential.assert_called_with(client_id=env["ELV_MI_APP_CLIENT_ID"])
                rbac.service_credential("audit")
                credential.assert_called_with(client_id=env["ELV_MI_AUDIT_CLIENT_ID"])
                with self.assertRaises(ValueError):
                    rbac.credential_for(None)

    def test_missing_malformed_and_duplicate_identity_are_rejected(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            personas = ["viewer", "designer", "approver", "app"]
            valid = identity_env(personas)
            for invalid in ("", "not-a-guid", valid["ELV_MI_VIEWER_CLIENT_ID"]):
                with self.subTest(poc=poc.name, invalid=invalid), patch.dict(
                    os.environ, {**valid, "ELV_MI_APP_CLIENT_ID": invalid}, clear=True
                ), patch.object(host, "ManagedIdentityCredential") as credential:
                    with self.assertRaises(ValueError):
                        host.managed_credential("app", personas)
                    credential.assert_not_called()

    def test_development_fallback_is_preserved_outside_vm_mode(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with patch.dict(sys.modules, {"hosting": host}):
                rbac = load_module("test_rbac", poc / "rbac.py")
            with self.subTest(poc=poc.name), patch.dict(os.environ, {}, clear=True), \
                    patch.object(rbac, "_roles_file", return_value={}), \
                    patch.object(rbac, "DefaultAzureCredential") as credential:
                self.assertFalse(rbac.personas_configured())
                self.assertIs(rbac.credential_for("viewer"), credential.return_value)
                self.assertIs(rbac.service_credential("runtime"), credential.return_value)

    def test_audit_resources_must_be_distinct_app_configuration_ids(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            resource = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/demo/providers/Microsoft.AppConfiguration/configurationStores/live"
            env = {
                "AZURE_APPCONFIG_RESOURCE_ID": resource,
                "AZURE_APPCONFIG_DRAFT_RESOURCE_ID": resource.replace("/live", "/draft"),
            }
            with self.subTest(poc=poc.name), patch.dict(os.environ, env, clear=True):
                self.assertEqual(len(host.audit_resource_ids()), 2)
                os.environ["AZURE_APPCONFIG_DRAFT_RESOURCE_ID"] = resource.upper()
                with self.assertRaises(ValueError):
                    host.audit_resource_ids()

    def test_vm_audit_uses_resource_context_and_merges_latest_rows(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with patch.dict(sys.modules, {"hosting": host}):
                rbac = load_module("test_rbac", poc / "rbac.py")
            with patch.dict(sys.modules, {"hosting": host, "rbac": rbac}):
                audit = load_module("test_audit", poc / "audit.py")
            responses = [
                SimpleNamespace(
                    status=audit.LogsQueryStatus.SUCCESS,
                    tables=[SimpleNamespace(columns=["TimeGenerated", "OperationName"], rows=rows)],
                ) for rows in ([["2026-09-08T01:00", "older"]], [["2026-09-08T02:00", "newer"]])
            ]
            with self.subTest(poc=poc.name), patch.dict(os.environ, identity_env(rbac.PERSONAS), clear=True), \
                    patch.object(audit, "LogsQueryClient") as client_type, \
                    patch.object(rbac, "service_credential"), \
                    patch.object(host, "audit_resource_ids", return_value=("/live", "/draft")):
                client = client_type.return_value
                client.query_resource.side_effect = responses
                columns, rows = audit.run_query(audit.CHANGES_QUERY)
                self.assertEqual(columns[0], "TimeGenerated")
                self.assertEqual(rows[0][1], "newer")
                client.query_workspace.assert_not_called()
                self.assertEqual(
                    [call.kwargs["resource_id"] for call in client.query_resource.call_args_list],
                    ["/live", "/draft"],
                )

    def test_partial_audit_response_is_not_reported_as_complete(self):
        for poc in POCS:
            host = load_module("test_host", poc / "hosting.py")
            with patch.dict(sys.modules, {"hosting": host}):
                rbac = load_module("test_rbac", poc / "rbac.py")
            with patch.dict(sys.modules, {"hosting": host, "rbac": rbac}):
                audit = load_module("test_audit", poc / "audit.py")
            with self.subTest(poc=poc.name), patch.dict(
                os.environ, {"ELV_HOSTING_MODE": "azure-vm"}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    audit._query_result(SimpleNamespace(status=audit.LogsQueryStatus.PARTIAL))


if __name__ == "__main__":
    unittest.main()