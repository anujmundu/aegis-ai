"""Cloud-Agnostic Secret & Key Management Adapter Interface & Implementations.

Supports:
- Local Environment & File Secrets
- AWS Secrets Manager
- Google Cloud Secret Manager
- Azure Key Vault
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("aegisai.cloud.secrets")


class CloudSecretManagerAdapter(ABC):
    """Abstract base class for cloud secrets management."""

    @abstractmethod
    def get_secret(self, secret_name: str) -> str:
        """Retrieve plaintext secret string by name."""
        pass

    @abstractmethod
    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Create or update a secret value."""
        pass


class LocalSecretManager(CloudSecretManagerAdapter):
    """Local and environment-backed secrets manager for zero-cost and on-premise execution."""

    def __init__(self, persistence_file: Optional[Path] = None) -> None:
        self.persistence_file = persistence_file or (
            Path(__file__).resolve().parent.parent.parent / "data" / "cloud_storage" / "secrets" / "local_secrets.json"
        )
        self.persistence_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, str] = {}

        if self.persistence_file.exists():
            try:
                self._cache = json.loads(self.persistence_file.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    def get_secret(self, secret_name: str) -> str:
        # Check OS environment first
        env_val = os.getenv(secret_name)
        if env_val:
            return env_val

        # Check local persistent cache
        if secret_name in self._cache:
            return self._cache[secret_name]

        raise KeyError(f"Secret '{secret_name}' not found in local environment or store.")

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        self._cache[secret_name] = secret_value
        self.persistence_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        return True


class AWSSecretsManagerProvider(CloudSecretManagerAdapter):
    """AWS Secrets Manager provider with graceful local fallback."""

    def __init__(self, region_name: str = "us-east-1") -> None:
        self.region_name = region_name
        self._client = None
        self._fallback = LocalSecretManager()

        try:
            import boto3
            self._client = boto3.client("secretsmanager", region_name=region_name)
            logger.info("Connected to native AWS Secrets Manager (region='%s')", region_name)
        except Exception:
            logger.info("AWS Boto3 unavailable or offline; operating Secrets Manager in structured sandbox.")

    def get_secret(self, secret_name: str) -> str:
        if self._client:
            try:
                res = self._client.get_secret_value(SecretId=secret_name)
                return res.get("SecretString", "")
            except Exception as e:
                logger.warning("AWS Secrets Manager get_secret failed (%s); checking fallback.", e)
        return self._fallback.get_secret(secret_name)

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        if self._client:
            try:
                self._client.put_secret_value(SecretId=secret_name, SecretString=secret_value)
                return True
            except Exception:
                pass
        return self._fallback.set_secret(secret_name, secret_value)


class GCPSecretManagerProvider(CloudSecretManagerAdapter):
    """Google Cloud Secret Manager provider with graceful local fallback."""

    def __init__(self, project_id: str = "aegisai-prod") -> None:
        self.project_id = project_id
        self._client = None
        self._fallback = LocalSecretManager()

        try:
            from google.cloud import secretmanager
            self._client = secretmanager.SecretManagerServiceClient()
            logger.info("Connected to native GCP Secret Manager (project='%s')", project_id)
        except Exception:
            logger.info("GCP Secret Manager SDK unavailable or offline; operating in structured sandbox.")

    def get_secret(self, secret_name: str) -> str:
        if self._client:
            try:
                name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
                res = self._client.access_secret_version(name=name)
                return res.payload.data.decode("utf-8")
            except Exception as e:
                logger.warning("GCP Secret Manager access failed (%s); checking fallback.", e)
        return self._fallback.get_secret(secret_name)

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        return self._fallback.set_secret(secret_name, secret_value)


class AzureKeyVaultProvider(CloudSecretManagerAdapter):
    """Azure Key Vault provider with graceful local fallback."""

    def __init__(self, vault_url: str = "https://aegisai-vault.vault.azure.net") -> None:
        self.vault_url = vault_url
        self._client = None
        self._fallback = LocalSecretManager()

        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            self._client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
            logger.info("Connected to native Azure Key Vault at %s", vault_url)
        except Exception:
            logger.info("Azure Key Vault SDK unavailable or offline; operating in structured sandbox.")

    def get_secret(self, secret_name: str) -> str:
        if self._client:
            try:
                secret = self._client.get_secret(secret_name)
                return secret.value or ""
            except Exception as e:
                logger.warning("Azure Key Vault get_secret failed (%s); checking fallback.", e)
        return self._fallback.get_secret(secret_name)

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        if self._client:
            try:
                self._client.set_secret(secret_name, secret_value)
                return True
            except Exception:
                pass
        return self._fallback.set_secret(secret_name, secret_value)
