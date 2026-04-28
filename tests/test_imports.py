"""Basic environment and imports verification test."""

def test_settings_import():
    from apps.api.config import settings

    assert settings.service_name == "aegis-ai"
    assert settings.api_port == 8000
    assert settings.min_model_precision == 0.90
    assert settings.max_p99_latency_ms == 15.0
