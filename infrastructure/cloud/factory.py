"""Unified Cloud Provider Factory for AegisAI.

Provides:
- Dynamic multi-cloud provider resolution (AWS, Azure, GCP, Local)
- Dependency injection container for cloud storage, monitoring, and secrets
"""

import logging
import os
from enum import Enum
from typing import Optional

from infrastructure.cloud.monitoring import (
    AWSCloudWatchProvider,
    AzureMonitorProvider,
    CloudMonitoringAdapter,
    GCPCloudMonitoringProvider,
    LocalPrometheusMonitoringProvider,
)
from infrastructure.cloud.secrets import (
    AWSSecretsManagerProvider,
    AzureKeyVaultProvider,
    CloudSecretManagerAdapter,
    GCPSecretManagerProvider,
    LocalSecretManager,
)
from infrastructure.cloud.storage import (
    AzureBlobStorageProvider,
    CloudStorageAdapter,
    GCSStorageProvider,
    LocalStorageProvider,
    S3StorageProvider,
)

logger = logging.getLogger("aegisai.cloud.factory")


class CloudProviderType(str, Enum):
    """Supported cloud infrastructure environments."""
    LOCAL = "local"
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class CloudProviderFactory:
    """Factory resolving appropriate cloud adapters based on active environment."""

    @staticmethod
    def detect_provider() -> CloudProviderType:
        """Inspect environment variables to determine active cloud provider."""
        env_val = os.getenv("CLOUD_PROVIDER", "").lower()
        if env_val in ("aws", "amazon"):
            return CloudProviderType.AWS
        elif env_val in ("gcp", "google"):
            return CloudProviderType.GCP
        elif env_val in ("azure", "microsoft"):
            return CloudProviderType.AZURE
        return CloudProviderType.LOCAL

    @classmethod
    def get_storage_adapter(
        cls,
        provider: Optional[CloudProviderType] = None,
        **kwargs,
    ) -> CloudStorageAdapter:
        """Instantiate cloud storage adapter for the target provider."""
        target = provider or cls.detect_provider()
        logger.info("Initializing CloudStorageAdapter for provider: %s", target.value)

        if target == CloudProviderType.AWS:
            bucket = kwargs.get("bucket_name", os.getenv("AWS_S3_BUCKET", "aegisai-incident-evidence"))
            region = kwargs.get("region_name", os.getenv("AWS_REGION", "us-east-1"))
            return S3StorageProvider(bucket_name=bucket, region_name=region)

        elif target == CloudProviderType.GCP:
            bucket = kwargs.get("bucket_name", os.getenv("GCP_STORAGE_BUCKET", "aegisai-gcs-evidence"))
            project = kwargs.get("project_id", os.getenv("GCP_PROJECT_ID", "aegisai-prod"))
            return GCSStorageProvider(bucket_name=bucket, project_id=project)

        elif target == CloudProviderType.AZURE:
            container = kwargs.get("container_name", os.getenv("AZURE_STORAGE_CONTAINER", "aegisai-evidence"))
            account = kwargs.get("account_name", os.getenv("AZURE_STORAGE_ACCOUNT", "aegisaistorage"))
            return AzureBlobStorageProvider(container_name=container, account_name=account)

        return LocalStorageProvider()

    @classmethod
    def get_monitoring_adapter(
        cls,
        provider: Optional[CloudProviderType] = None,
        **kwargs,
    ) -> CloudMonitoringAdapter:
        """Instantiate cloud metrics and monitoring adapter."""
        target = provider or cls.detect_provider()
        logger.info("Initializing CloudMonitoringAdapter for provider: %s", target.value)

        if target == CloudProviderType.AWS:
            namespace = kwargs.get("namespace", os.getenv("AWS_CLOUDWATCH_NAMESPACE", "AegisAI/Telemetry"))
            region = kwargs.get("region_name", os.getenv("AWS_REGION", "us-east-1"))
            return AWSCloudWatchProvider(namespace=namespace, region_name=region)

        elif target == CloudProviderType.GCP:
            project = kwargs.get("project_id", os.getenv("GCP_PROJECT_ID", "aegisai-prod"))
            return GCPCloudMonitoringProvider(project_id=project)

        elif target == CloudProviderType.AZURE:
            key = kwargs.get("instrumentation_key", os.getenv("APPINSIGHTS_KEY", "aegisai-mock-key"))
            return AzureMonitorProvider(instrumentation_key=key)

        return LocalPrometheusMonitoringProvider()

    @classmethod
    def get_secret_manager(
        cls,
        provider: Optional[CloudProviderType] = None,
        **kwargs,
    ) -> CloudSecretManagerAdapter:
        """Instantiate cloud secret manager adapter."""
        target = provider or cls.detect_provider()
        logger.info("Initializing CloudSecretManagerAdapter for provider: %s", target.value)

        if target == CloudProviderType.AWS:
            region = kwargs.get("region_name", os.getenv("AWS_REGION", "us-east-1"))
            return AWSSecretsManagerProvider(region_name=region)

        elif target == CloudProviderType.GCP:
            project = kwargs.get("project_id", os.getenv("GCP_PROJECT_ID", "aegisai-prod"))
            return GCPSecretManagerProvider(project_id=project)

        elif target == CloudProviderType.AZURE:
            vault_url = kwargs.get("vault_url", os.getenv("AZURE_KEYVAULT_URL", "https://aegisai-vault.vault.azure.net"))
            return AzureKeyVaultProvider(vault_url=vault_url)

        return LocalSecretManager()
