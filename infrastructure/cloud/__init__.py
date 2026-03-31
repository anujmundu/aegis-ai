"""Cloud-Agnostic Multi-Cloud Adapters for AegisAI (AWS, GCP, Azure, Local)."""

from infrastructure.cloud.factory import CloudProviderFactory, CloudProviderType
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

__all__ = [
    "CloudProviderFactory",
    "CloudProviderType",
    "CloudStorageAdapter",
    "LocalStorageProvider",
    "S3StorageProvider",
    "GCSStorageProvider",
    "AzureBlobStorageProvider",
    "CloudMonitoringAdapter",
    "LocalPrometheusMonitoringProvider",
    "AWSCloudWatchProvider",
    "GCPCloudMonitoringProvider",
    "AzureMonitorProvider",
    "CloudSecretManagerAdapter",
    "LocalSecretManager",
    "AWSSecretsManagerProvider",
    "GCPSecretManagerProvider",
    "AzureKeyVaultProvider",
]
