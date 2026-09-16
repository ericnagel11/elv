"""Deployment contract tests; execute with unittest on the target VM."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()