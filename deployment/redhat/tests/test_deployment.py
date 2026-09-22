"""Deployment contract tests; execute with unittest on the target VM."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

DEPLOY = Path(__file__).resolve().parents[1]


def load_launcher():
    spec = importlib.util.spec_from_file_location("elv_launcher", DEPLOY / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeploymentContracts(unittest.TestCase):
    def test_full_demo_configuration_is_required_without_echoing_values(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as state:
            settings = {
                "AZURE_APPCONFIG_ENDPOINT": "https://live.azconfig.io",
                "AZURE_APPCONFIG_DRAFT_ENDPOINT": "https://draft.azconfig.io",
                "AZURE_OPENAI_ENDPOINT": "https://model.openai.azure.com/",
                "AZURE_SEARCH_ENDPOINT": "https://search.search.windows.net",
                "AZURE_LANGUAGE_ENDPOINT": "https://language.cognitiveservices.azure.com/",
                "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
                "AZURE_LOG_ANALYTICS_WORKSPACE_ID": "00000000-0000-4000-8000-000000000002",
                "AZURE_OPENAI_DEPLOYMENT": "approved-deployment",
                "AZURE_OPENAI_API_VERSION": "2024-10-21",
                "ELV_STATE_DIRECTORY": state,
            }
            with patch.dict(os.environ, settings, clear=True):
                launcher.validate_settings("002")
                os.environ.pop("AZURE_LANGUAGE_ENDPOINT")
                with self.assertRaisesRegex(ValueError, "AZURE_LANGUAGE_ENDPOINT"):
                    launcher.validate_settings("002")
                # Language is intentionally not part of PoC001.
                launcher.validate_settings("001")
                os.environ["AZURE_CLIENT_SECRET"] = "synthetic-test-value-not-a-credential"
                with self.assertRaises(ValueError) as error:
                    launcher.validate_settings("001")
                self.assertNotIn("synthetic-test-value", str(error.exception))
                self.assertIn("AZURE_CLIENT_SECRET", str(error.exception))

    def test_live_draft_collision_is_rejected(self):
        launcher = load_launcher()
        with patch.dict(os.environ, {
            "AZURE_APPCONFIG_ENDPOINT": "https://same.azconfig.io/",
            "AZURE_APPCONFIG_DRAFT_ENDPOINT": "https://same.azconfig.io",
            "AZURE_OPENAI_ENDPOINT": "https://model.openai.azure.com/",
            "AZURE_SEARCH_ENDPOINT": "https://search.search.windows.net",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "different stores"):
                launcher.validate_settings("001")

    def test_commands_bind_loopback_and_use_separate_ports(self):
        launcher = load_launcher()
        for poc, port in (("001", "8501"), ("002", "8502")):
            command = launcher.command_for(poc, "ui", "/python", Path("/app"))
            self.assertIn("--server.address=127.0.0.1", command)
            self.assertIn(f"--server.port={port}", command)
            self.assertIn("--server.enableXsrfProtection=true", command)
            self.assertIn("--server.enableCORS=true", command)
            self.assertIn("--server.headless=true", command)
        agent = launcher.command_for("001", "agent", "/python", Path("/app"))
        self.assertEqual(agent[agent.index("--host") + 1], "127.0.0.1")
        self.assertEqual(agent[agent.index("--port") + 1], "9999")
        with self.assertRaises(ValueError):
            launcher.command_for("002", "agent", "/python", Path("/app"))

    def test_units_run_nonroot_and_do_not_write_source(self):
        units = list((DEPLOY / "systemd").glob("*.service"))
        self.assertEqual(len(units), 3)
        for unit in units:
            text = unit.read_text(encoding="utf-8")
            with self.subTest(unit=unit.name):
                self.assertIn("User=elv-poc", text)
                self.assertIn("ProtectSystem=strict", text)
                self.assertIn("NoNewPrivileges=true", text)
                self.assertIn("EnvironmentFile=/etc/elv/", text)
                self.assertIn("StateDirectory=elv-poc", text)
                self.assertIn("CacheDirectory=elv-poc", text)
                self.assertNotIn("ReadWritePaths=/opt/elv", text)
                self.assertNotIn("0.0.0.0", text)

    def test_linux_scripts_have_lf_line_endings(self):
        for path in (DEPLOY / "prepare-environments.sh", DEPLOY / "install-services.sh"):
            self.assertNotIn(b"\r", path.read_bytes())


class AuditBackendDeploymentContracts(unittest.TestCase):
    """Offline launcher checks: no PoC/SDK imports, processes or Azure calls."""

    @staticmethod
    def settings(state):
        return {
            "AZURE_APPCONFIG_ENDPOINT": "https://live.azconfig.io",
            "AZURE_APPCONFIG_DRAFT_ENDPOINT": "https://draft.azconfig.io",
            "AZURE_OPENAI_ENDPOINT": "https://model.openai.azure.com/",
            "AZURE_SEARCH_ENDPOINT": "https://search.search.windows.net",
            "AZURE_LANGUAGE_ENDPOINT": "https://language.cognitiveservices.azure.com/",
            "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
            "AZURE_OPENAI_DEPLOYMENT": "approved-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
            "ELV_STATE_DIRECTORY": state,
        }

    def test_poc001_default_and_explicit_blob_need_no_la_settings(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as state:
            for backend in (None, "blob", " BLOB "):
                for workspace in (None, "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
                    settings = self.settings(state)
                    if backend is not None:
                        settings["ELV_AUDIT_BACKEND"] = backend
                    if workspace is not None:
                        settings["AZURE_LOG_ANALYTICS_WORKSPACE_ID"] = workspace
                    with self.subTest(backend=backend, workspace=workspace), patch.dict(
                        os.environ, settings, clear=True
                    ):
                        self.assertFalse(launcher.uses_log_analytics("001"))
                        launcher.validate_settings("001")

    def test_la_requires_nonzero_workspace_for_001_and_always_for_002(self):
        launcher = load_launcher()
        cases = [("001", "loganalytics"), ("001", " LogAnalytics ")]
        cases.extend(("002", backend) for backend in (None, "blob", "loganalytics", "", "invalid"))
        with tempfile.TemporaryDirectory() as state:
            for poc, backend in cases:
                settings = self.settings(state)
                if backend is not None:
                    settings["ELV_AUDIT_BACKEND"] = backend
                for workspace in (None, "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
                    env = dict(settings)
                    if workspace is not None:
                        env["AZURE_LOG_ANALYTICS_WORKSPACE_ID"] = workspace
                    with self.subTest(poc=poc, backend=backend, workspace=workspace), patch.dict(
                        os.environ, env, clear=True
                    ):
                        self.assertTrue(launcher.uses_log_analytics(poc))
                        with self.assertRaisesRegex(ValueError, "AZURE_LOG_ANALYTICS_WORKSPACE_ID") as error:
                            launcher.validate_settings(poc)
                        if workspace:
                            self.assertNotIn(workspace, str(error.exception))
                settings["AZURE_LOG_ANALYTICS_WORKSPACE_ID"] = "00000000-0000-4000-8000-000000000002"
                with patch.dict(os.environ, settings, clear=True):
                    launcher.validate_settings(poc)

    def test_poc001_blob_settings_and_writer_are_not_startup_requirements(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as state:
            for backend in (None, "blob", "", "invalid"):
                for blob_settings in ({}, {
                    "ELV_AUDIT_BLOB_ACCOUNT_URL": "invalid-endpoint",
                    "ELV_AUDIT_BLOB_CONTAINER": "INVALID_CONTAINER",
                    "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": "not-a-uuid",
                }, {
                    # Even a colliding writer is checked lazily, not here.
                    "ELV_MI_AUDIT_CLIENT_ID": "00000000-0000-4000-8000-000000000005",
                    "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": "00000000-0000-4000-8000-000000000005",
                }):
                    settings = {**self.settings(state), **blob_settings}
                    if backend is not None:
                        settings["ELV_AUDIT_BACKEND"] = backend
                    with self.subTest(backend=backend, blob_settings=blob_settings), patch.dict(
                        os.environ, settings, clear=True
                    ):
                        launcher.validate_settings("001")

    def test_blob_mode_still_requires_valid_tenant_and_normal_settings(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as state:
            for key, invalid in (
                ("AZURE_TENANT_ID", ""),
                ("AZURE_TENANT_ID", "00000000-0000-0000-0000-000000000000"),
                ("AZURE_TENANT_ID", "not-a-uuid"),
                ("AZURE_SEARCH_ENDPOINT", "http://search.search.windows.net"),
                ("AZURE_OPENAI_DEPLOYMENT", ""),
                ("ELV_STATE_DIRECTORY", "relative-state"),
            ):
                with self.subTest(key=key, invalid=invalid), patch.dict(
                    os.environ, {**self.settings(state), key: invalid}, clear=True
                ):
                    with self.assertRaisesRegex(ValueError, key):
                        launcher.validate_settings("001")

    def test_main_only_checks_audit_resources_in_la_mode_and_always_checks_personas(self):
        launcher = load_launcher()
        cases = [
            ("001", None, False), ("001", "blob", False),
            ("001", "invalid", False), ("001", " LogAnalytics ", True),
            ("002", None, True), ("002", "blob", True),
            ("002", "loganalytics", True), ("002", "invalid", True),
        ]
        with tempfile.TemporaryDirectory() as state:
            for poc, backend, requires_la in cases:
                for component in (("ui", "agent") if poc == "001" else ("ui",)):
                    settings = self.settings(state)
                    if backend is not None:
                        settings["ELV_AUDIT_BACKEND"] = backend
                    if requires_la:
                        settings["AZURE_LOG_ANALYTICS_WORKSPACE_ID"] = "00000000-0000-4000-8000-000000000002"
                    host = SimpleNamespace(identity_ids=Mock(), audit_resource_ids=Mock())
                    rbac = SimpleNamespace(PERSONAS={"viewer": {}, "designer": {}, "approver": {}, "app": {}})
                    if poc == "002":
                        rbac.PERSONAS["market_owner"] = {}
                    with self.subTest(poc=poc, backend=backend, component=component), \
                            patch.dict(os.environ, settings, clear=True), \
                            patch.dict(sys.modules, {"hosting": host, "rbac": rbac}), \
                            patch.object(sys, "argv", ["run.py", "--poc", poc, "--component", component]), \
                            patch.object(sys, "path", list(sys.path)), \
                            patch.object(sys, "platform", "linux"), \
                            patch.object(os, "geteuid", return_value=1000, create=True), \
                            patch.object(os, "chdir") as chdir, patch.object(os, "execv") as execute:
                        launcher.main()
                        host.identity_ids.assert_called_once_with(rbac.PERSONAS)
                        if requires_la:
                            host.audit_resource_ids.assert_called_once_with()
                        else:
                            host.audit_resource_ids.assert_not_called()
                        self.assertEqual(os.environ["ELV_HOSTING_MODE"], "azure-vm")
                        self.assertEqual(os.environ["A2A_AGENT_URL"], "http://127.0.0.1:9999")
                        chdir.assert_called_once()
                        execute.assert_called_once()

    def test_main_validation_failures_prevent_launch(self):
        launcher = load_launcher()
        cases = [
            ("001", "blob", "identity_ids"),
            ("001", "loganalytics", "identity_ids"),
            ("001", "loganalytics", "audit_resource_ids"),
            ("002", "blob", "identity_ids"),
            ("002", "blob", "audit_resource_ids"),
        ]
        with tempfile.TemporaryDirectory() as state:
            for poc, backend, failing_check in cases:
                settings = {
                    **self.settings(state), "ELV_AUDIT_BACKEND": backend,
                    "AZURE_LOG_ANALYTICS_WORKSPACE_ID": "00000000-0000-4000-8000-000000000002",
                }
                host = SimpleNamespace(identity_ids=Mock(), audit_resource_ids=Mock())
                getattr(host, failing_check).side_effect = ValueError(failing_check)
                with self.subTest(poc=poc, backend=backend, failing_check=failing_check), \
                        patch.dict(os.environ, settings, clear=True), \
                        patch.dict(sys.modules, {"hosting": host, "rbac": SimpleNamespace(PERSONAS={})}), \
                        patch.object(sys, "argv", ["run.py", "--poc", poc, "--component", "ui"]), \
                        patch.object(sys, "path", list(sys.path)), \
                        patch.object(sys, "platform", "linux"), \
                        patch.object(os, "geteuid", return_value=1000, create=True), \
                        patch.object(os, "chdir") as chdir, patch.object(os, "execv") as execute:
                    with self.assertRaisesRegex(ValueError, failing_check):
                        launcher.main()
                    chdir.assert_not_called()
                    execute.assert_not_called()

    def test_windows_is_not_a_supported_launcher_platform(self):
        launcher = load_launcher()
        with patch.object(sys, "argv", ["run.py", "--poc", "001", "--component", "ui"]), \
                patch.object(sys, "platform", "win32"), patch.object(os, "execv") as execute:
            with self.assertRaisesRegex(ValueError, "approved Linux VM"):
                launcher.main()
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()