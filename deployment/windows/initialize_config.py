"""Preview or explicitly create experience or approved existing-index knowledge settings."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.identity import ManagedIdentityCredential

from run import PROJECT, ROOT, _unique_settings, load_settings, process_environment

sys.path.insert(0, str(PROJECT))
import config as cfg
from prompt import _load_asset


class InitializationConflict(RuntimeError):
    """An existing entry differs from the approved synthetic setting."""


def sample_settings() -> list:
    settings = []
    sample_keys = ("persona", "tone", "verbosity", "reading_level", "response_structure")
    for label, asset in (("baseline", "response:v1"), ("candidate", "response:v2")):
        metadata, _ = _load_asset(asset)
        sample = metadata.get("sample") or {}
        for name in sample_keys:
            value = sample.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"The {asset} synthetic sample is missing {name}.")
            settings.append(ConfigurationSetting(key=f"experience:{name}", label=label, value=value))
        settings.append(ConfigurationSetting(key="experience:prompt_asset", label=label, value=asset))
    return settings


def knowledge_settings(path: Path, runtime: dict) -> list:
    if runtime.get("ELV_ENABLE_RAG") != "true":
        raise ValueError("Enable RAG and its approved index list in runtime JSON before preparing knowledge settings.")
    if path.resolve().is_relative_to(ROOT) or path.suffix.lower() != ".json":
        raise ValueError("Use an explicit knowledge profile JSON outside the checkout.")
    try:
        with path.open(encoding="utf-8-sig") as handle:
            profile = json.load(handle, object_pairs_hook=_unique_settings)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Cannot read knowledge profile JSON; check its path, permissions and syntax.") from None
    if not isinstance(profile, dict) or set(profile) != set(cfg.COMPARISON_KNOWLEDGE_KEYS):
        raise ValueError("Knowledge profile JSON must contain exactly the documented knowledge setting names.")
    approved = [name.strip() for name in runtime.get("ELV_SEARCH_ALLOWED_INDEXES", "").split(",")]
    if profile.get("index") not in approved:
        raise ValueError("The knowledge profile must select an index approved in runtime JSON.")
    for key, value in profile.items():
        if key != "index":
            cfg.validate_knowledge_value(key, value)
    return [
        ConfigurationSetting(key=f"knowledge:{key}", label=label, value=profile[key])
        for label in cfg.PROFILE_LABELS for key in cfg.COMPARISON_KNOWLEDGE_KEYS
    ]


def _verify_value(actual, expected) -> None:
    if actual is None or actual.value != expected.value:
        raise InitializationConflict(
            f"CONFLICT: {expected.label}/{expected.key}; existing content was not overwritten."
        )


def initialize(client, settings: list) -> tuple:
    missing = []
    for setting in settings:
        try:
            actual = client.get_configuration_setting(key=setting.key, label=setting.label)
        except ResourceNotFoundError:
            missing.append(setting)
        else:
            _verify_value(actual, setting)

    created = 0
    for setting in missing:
        try:
            client.add_configuration_setting(setting)
        except ResourceExistsError:
            actual = client.get_configuration_setting(key=setting.key, label=setting.label)
            _verify_value(actual, setting)
        else:
            created += 1
            print(f"CREATED: {setting.label}/{setting.key}")

    for setting in settings:
        actual = client.get_configuration_setting(key=setting.key, label=setting.label)
        _verify_value(actual, setting)
    return created, len(settings) - created


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--knowledge-config", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-azure-host", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and (sys.platform != "win32" or not args.approved_azure_host):
        raise ValueError("Applying requires the approved Azure Windows VM and --approved-azure-host.")
    runtime = load_settings(args.config)
    settings = knowledge_settings(args.knowledge_config, runtime) if args.knowledge_config else sample_settings()
    print(f"Target store: {runtime['AZURE_APPCONFIG_ENDPOINT']}")
    for setting in settings:
        print(f"{setting.label:9} {setting.key:30} {setting.value}")
    if not args.apply:
        print(f"PREVIEW_ONLY: {len(settings)} proposed entries; no credentials, Azure reads or writes.")
        return 0

    os.environ.update(process_environment(runtime))
    logging.getLogger("azure").setLevel(logging.CRITICAL)
    with ManagedIdentityCredential(client_id=runtime["ELV_MI_APP_CLIENT_ID"].strip()) as credential:
        with AzureAppConfigurationClient(
            base_url=runtime["AZURE_APPCONFIG_ENDPOINT"], credential=credential,
            retry_total=0, connection_timeout=10, read_timeout=30,
        ) as client:
            created, preserved = initialize(client, settings)
    print(f"INITIALIZATION_SUCCEEDED: {len(settings)} verified; created={created}; preserved={preserved}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"INITIALIZATION_INPUT_ERROR: {error}", file=sys.stderr)
        sys.exit(2)
    except InitializationConflict as error:
        print(str(error), file=sys.stderr)
        print("No rollback was attempted; earlier creates may remain. Review before rerunning.", file=sys.stderr)
        sys.exit(4)
    except ClientAuthenticationError:
        print("INITIALIZATION_AUTH_FAILED: verify VM attachment and managed identity Client ID.", file=sys.stderr)
        sys.exit(3)
    except HttpResponseError as error:
        status = error.status_code if isinstance(error.status_code, int) else "UNKNOWN"
        print(f"INITIALIZATION_FAILED: HTTP {status}; verify store access and Data Owner permission.", file=sys.stderr)
        print("Earlier creates may remain; no overwrite or rollback was attempted.", file=sys.stderr)
        sys.exit(4)
    except AzureError:
        print("INITIALIZATION_FAILED: verify identity, private routing, proxy and CA trust.", file=sys.stderr)
        print("Earlier creates may remain; no overwrite or rollback was attempted.", file=sys.stderr)
        sys.exit(4)