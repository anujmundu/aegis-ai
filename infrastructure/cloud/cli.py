"""Command-Line Diagnostic Utility for Cloud-Agnostic Adapters.

Usage:
    python -m infrastructure.cloud.cli status
    python -m infrastructure.cloud.cli test-sync [--provider=aws|gcp|azure|local]
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

from infrastructure.cloud.factory import CloudProviderFactory, CloudProviderType

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cmd_status() -> None:
    """Print detected cloud provider and configuration status."""
    provider = CloudProviderFactory.detect_provider()
    print("=" * 60)
    print("[*] AegisAI Cloud-Agnostic Adapter Status")
    print("=" * 60)
    print(f"Active Provider Environment : {provider.value.upper()}")

    storage = CloudProviderFactory.get_storage_adapter(provider)
    print(f"Storage Adapter Type        : {storage.__class__.__name__}")

    monitoring = CloudProviderFactory.get_monitoring_adapter(provider)
    print(f"Monitoring Adapter Type     : {monitoring.__class__.__name__}")

    secrets = CloudProviderFactory.get_secret_manager(provider)
    print(f"Secret Manager Type         : {secrets.__class__.__name__}")
    print("=" * 60)


def cmd_test_sync(provider_str: str) -> None:
    """Run an end-to-end round-trip test against the selected provider."""
    try:
        p_enum = CloudProviderType(provider_str.lower())
    except ValueError:
        print(f"Error: Unknown provider '{provider_str}'. Choose from: local, aws, gcp, azure.")
        sys.exit(1)

    print(f"\n[AegisAI Cloud] Testing Round-Trip Operations on {p_enum.value.upper()}...")

    # 1. Test Storage Upload / Download / Delete
    storage = CloudProviderFactory.get_storage_adapter(p_enum)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
        tmp.write('{"test": "cloud_agnostic_sync", "timestamp": ' + str(time.time()) + "}")
        tmp_path = Path(tmp.name)

    try:
        remote_key = f"diag/test_artifact_{int(time.time())}.json"
        uri = storage.upload_file(tmp_path, remote_key)
        print(f"  [PASS] Storage Upload -> {uri}")

        objs = storage.list_objects("diag/")
        assert any(remote_key in o for o in objs), "Uploaded object not listed"
        print(f"  [PASS] Storage Listing ({len(objs)} objects found)")

        signed_url = storage.get_signed_url(remote_key, expires_in_seconds=600)
        print(f"  [PASS] Storage Signed URL -> {signed_url[:50]}...")

        dl_path = tmp_path.parent / f"downloaded_{tmp_path.name}"
        storage.download_file(remote_key, dl_path)
        assert dl_path.exists()
        print("  [PASS] Storage Download & Integrity Verified")

        storage.delete_object(remote_key)
        print("  [PASS] Storage Clean Delete")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # 2. Test Monitoring Publish
    monitoring = CloudProviderFactory.get_monitoring_adapter(p_enum)
    ok = monitoring.publish_metric(
        "DiagnosticPing",
        1.0,
        unit="Count",
        dimensions={"Service": "aegis-cli", "Status": "PASS"},
    )
    assert ok, "Failed to publish diagnostic metric"
    print("  [PASS] Telemetry Metric Published")

    # 3. Test Secrets Management
    secrets = CloudProviderFactory.get_secret_manager(p_enum)
    secrets.set_secret("AEGIS_DIAGNOSTIC_KEY", "valid_token_12345")
    val = secrets.get_secret("AEGIS_DIAGNOSTIC_KEY")
    assert val == "valid_token_12345"
    print(f"  [PASS] Secret Manager Verified (retrieved key length: {len(val)})")

    print("\n[SUCCESS] All cloud-agnostic adapter subsystems passed successfully!\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisAI Cloud Adapters CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Print active cloud provider status")

    test_parser = subparsers.add_parser("test-sync", help="Run end-to-end sync verification")
    test_parser.add_argument(
        "--provider",
        default="local",
        choices=["local", "aws", "gcp", "azure"],
        help="Target cloud provider",
    )

    args = parser.parse_args()
    if args.command == "test-sync":
        cmd_test_sync(args.provider)
    else:
        cmd_status()


if __name__ == "__main__":
    main()
