"""Unit and Integration Tests for Cloud-Agnostic Adapters (Phase 12).

Covers:
- Cloud Storage Adapters (Local, AWS S3, GCP Cloud Storage, Azure Blob Storage)
- Cloud Monitoring Adapters (Local Prometheus, AWS CloudWatch, GCP Monitoring, Azure Monitor)
- Cloud Secret Managers (Local, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault)
- Cloud Provider Factory dynamic environment resolution
- Cloud CLI diagnostic runner
"""

from pathlib import Path

import pytest

from infrastructure.cloud.cli import cmd_status, cmd_test_sync
from infrastructure.cloud.factory import CloudProviderFactory, CloudProviderType
from infrastructure.cloud.monitoring import (
    AWSCloudWatchProvider,
    AzureMonitorProvider,
    GCPCloudMonitoringProvider,
    LocalPrometheusMonitoringProvider,
)
from infrastructure.cloud.secrets import (
    AWSSecretsManagerProvider,
    AzureKeyVaultProvider,
    GCPSecretManagerProvider,
    LocalSecretManager,
)
from infrastructure.cloud.storage import (
    AzureBlobStorageProvider,
    GCSStorageProvider,
    LocalStorageProvider,
    S3StorageProvider,
)


class TestCloudStorageAdapters:
    """Validates multi-cloud object storage adapters."""

    @pytest.fixture
    def sample_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "telemetry_artifact.json"
        f.write_text('{"event": "db_pool_leak", "status": "resolved"}', encoding="utf-8")
        return f

    def test_local_storage_lifecycle(self, tmp_path: Path, sample_file: Path):
        storage = LocalStorageProvider(base_dir=tmp_path / "local_store")
        remote_key = "incidents/2026/01/incident_001.json"

        # 1. Upload
        uri = storage.upload_file(sample_file, remote_key)
        assert uri.startswith("file:///")

        # 2. List
        keys = storage.list_objects("incidents/")
        assert remote_key in keys

        # 3. Signed URL
        signed_url = storage.get_signed_url(remote_key, expires_in_seconds=1800)
        assert "expires=" in signed_url
        assert "sig=" in signed_url

        # 4. Download
        download_target = tmp_path / "downloaded.json"
        res_path = storage.download_file(remote_key, download_target)
        assert res_path.exists()
        assert res_path.read_text(encoding="utf-8") == sample_file.read_text(encoding="utf-8")

        # 5. Delete
        assert storage.delete_object(remote_key) is True
        assert storage.delete_object(remote_key) is False

    def test_aws_s3_storage_provider(self, tmp_path: Path, sample_file: Path):
        storage = S3StorageProvider(bucket_name="test-s3-bucket", base_dir=tmp_path / "s3")
        remote_key = "models/weights.bin"

        uri = storage.upload_file(sample_file, remote_key)
        assert uri == "s3://test-s3-bucket/models/weights.bin"

        keys = storage.list_objects("models/")
        assert remote_key in keys

        url = storage.get_signed_url(remote_key)
        assert "s3" in url

        dl = tmp_path / "dl_s3.bin"
        storage.download_file(remote_key, dl)
        assert dl.exists()

        assert storage.delete_object(remote_key) is True

    def test_gcp_storage_provider(self, tmp_path: Path, sample_file: Path):
        storage = GCSStorageProvider(bucket_name="test-gcs-bucket", base_dir=tmp_path / "gcs")
        remote_key = "evidence/trace_01.json"

        uri = storage.upload_file(sample_file, remote_key)
        assert uri == "gs://test-gcs-bucket/evidence/trace_01.json"

        keys = storage.list_objects("evidence/")
        assert remote_key in keys

        dl = tmp_path / "dl_gcs.json"
        storage.download_file(remote_key, dl)
        assert dl.exists()

        assert storage.delete_object(remote_key) is True

    def test_azure_blob_storage_provider(self, tmp_path: Path, sample_file: Path):
        storage = AzureBlobStorageProvider(container_name="test-container", base_dir=tmp_path / "azure")
        remote_key = "postmortems/pm_001.md"

        uri = storage.upload_file(sample_file, remote_key)
        assert "blob.core.windows.net" in uri

        keys = storage.list_objects("postmortems/")
        assert remote_key in keys

        dl = tmp_path / "dl_azure.md"
        storage.download_file(remote_key, dl)
        assert dl.exists()

        assert storage.delete_object(remote_key) is True


class TestCloudMonitoringAdapters:
    """Validates multi-cloud telemetry and alert publishers."""

    def test_local_prometheus_monitoring(self):
        adapter = LocalPrometheusMonitoringProvider()
        assert adapter.publish_metric("InferenceLatency", 1.25, unit="Milliseconds") is True
        assert adapter.publish_batch_metrics([
            {"metric_name": "CPU", "value": 45.0},
            {"metric_name": "Memory", "value": 78.0},
        ]) == 2
        alarm = adapter.create_alarm("HighCPU", "CPU", 80.0)
        assert alarm["status"] == "CONFIGURED"

    def test_aws_cloudwatch_monitoring(self):
        adapter = AWSCloudWatchProvider(namespace="AegisAI/Test")
        assert adapter.publish_metric("AppErrors", 2.0, dimensions={"Env": "test"}) is True
        assert len(adapter.mock_history) == 1
        alarm = adapter.create_alarm("ElevatedErrors", "AppErrors", 5.0)
        assert alarm["status"] == "ACTIVE"

    def test_gcp_cloud_monitoring(self):
        adapter = GCPCloudMonitoringProvider(project_id="test-proj")
        assert adapter.publish_metric("DiskIO", 120.5, dimensions={"host": "vm-1"}) is True
        assert len(adapter.mock_history) == 1
        alarm = adapter.create_alarm("HighDiskIO", "DiskIO", 200.0)
        assert alarm["provider"] == "gcp_cloud_monitoring"

    def test_azure_monitor(self):
        adapter = AzureMonitorProvider()
        assert adapter.publish_metric("OrdersPerSec", 85.0) is True
        assert len(adapter.mock_history) == 1
        alarm = adapter.create_alarm("LowOrders", "OrdersPerSec", 20.0)
        assert alarm["provider"] == "azure_monitor"


class TestCloudSecretManagers:
    """Validates multi-cloud secret manager adapters."""

    def test_local_secret_manager(self, tmp_path: Path):
        mgr = LocalSecretManager(persistence_file=tmp_path / "secrets.json")
        mgr.set_secret("DATABASE_KEY", "secret_pass_123")
        assert mgr.get_secret("DATABASE_KEY") == "secret_pass_123"

        with pytest.raises(KeyError):
            mgr.get_secret("NON_EXISTENT_KEY")

    def test_cloud_secret_manager_fallbacks(self):
        aws_mgr = AWSSecretsManagerProvider()
        aws_mgr.set_secret("AWS_TEST_KEY", "aws_val")
        assert aws_mgr.get_secret("AWS_TEST_KEY") == "aws_val"

        gcp_mgr = GCPSecretManagerProvider()
        gcp_mgr.set_secret("GCP_TEST_KEY", "gcp_val")
        assert gcp_mgr.get_secret("GCP_TEST_KEY") == "gcp_val"

        azure_mgr = AzureKeyVaultProvider()
        azure_mgr.set_secret("AZURE_TEST_KEY", "azure_val")
        assert azure_mgr.get_secret("AZURE_TEST_KEY") == "azure_val"


class TestCloudProviderFactory:
    """Validates dynamic cloud environment resolution."""

    def test_provider_detection(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        assert CloudProviderFactory.detect_provider() == CloudProviderType.AWS

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        assert CloudProviderFactory.detect_provider() == CloudProviderType.GCP

        monkeypatch.setenv("CLOUD_PROVIDER", "azure")
        assert CloudProviderFactory.detect_provider() == CloudProviderType.AZURE

        monkeypatch.delenv("CLOUD_PROVIDER", raising=False)
        assert CloudProviderFactory.detect_provider() == CloudProviderType.LOCAL

    def test_factory_instantiation(self):
        # Local
        assert isinstance(CloudProviderFactory.get_storage_adapter(CloudProviderType.LOCAL), LocalStorageProvider)
        assert isinstance(CloudProviderFactory.get_monitoring_adapter(CloudProviderType.LOCAL), LocalPrometheusMonitoringProvider)
        assert isinstance(CloudProviderFactory.get_secret_manager(CloudProviderType.LOCAL), LocalSecretManager)

        # AWS
        assert isinstance(CloudProviderFactory.get_storage_adapter(CloudProviderType.AWS), S3StorageProvider)
        assert isinstance(CloudProviderFactory.get_monitoring_adapter(CloudProviderType.AWS), AWSCloudWatchProvider)
        assert isinstance(CloudProviderFactory.get_secret_manager(CloudProviderType.AWS), AWSSecretsManagerProvider)

        # GCP
        assert isinstance(CloudProviderFactory.get_storage_adapter(CloudProviderType.GCP), GCSStorageProvider)
        assert isinstance(CloudProviderFactory.get_monitoring_adapter(CloudProviderType.GCP), GCPCloudMonitoringProvider)
        assert isinstance(CloudProviderFactory.get_secret_manager(CloudProviderType.GCP), GCPSecretManagerProvider)

        # Azure
        assert isinstance(CloudProviderFactory.get_storage_adapter(CloudProviderType.AZURE), AzureBlobStorageProvider)
        assert isinstance(CloudProviderFactory.get_monitoring_adapter(CloudProviderType.AZURE), AzureMonitorProvider)
        assert isinstance(CloudProviderFactory.get_secret_manager(CloudProviderType.AZURE), AzureKeyVaultProvider)


class TestCloudCLI:
    """Validates CLI diagnostic runner for all cloud providers."""

    def test_cli_status(self, capsys):
        cmd_status()
        captured = capsys.readouterr()
        assert "AegisAI Cloud-Agnostic Adapter Status" in captured.out
        assert "Storage Adapter Type" in captured.out

    @pytest.mark.parametrize("provider", ["local", "aws", "gcp", "azure"])
    def test_cli_test_sync(self, provider: str, capsys):
        cmd_test_sync(provider)
        captured = capsys.readouterr()
        assert f"Testing Round-Trip Operations on {provider.upper()}" in captured.out
        assert "Storage Upload" in captured.out
        assert "Telemetry Metric Published" in captured.out
        assert "All cloud-agnostic adapter subsystems passed" in captured.out
