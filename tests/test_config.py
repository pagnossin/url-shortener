import pytest

from app.config import Settings
from app.errors import ConfigurationError


def test_defaults_are_valid():
    Settings()


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "myurlshortener.com"},
        {"base_url": "ftp://myurlshortener.com"},
        {"expiration_seconds": 0},
        {"code_length": 3},
        {"code_length": 33},
        {"retention_seconds": -1},
        {"mongo_timeout_ms": 0},
        {"mongo_max_pool_size": 0},
        {"cache_max_entries": -1},
    ],
)
def test_invalid_settings_fail_fast(overrides):
    with pytest.raises(ConfigurationError):
        Settings(**overrides)


def test_from_env(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://sho.rt/")
    monkeypatch.setenv("EXPIRATION_SECONDS", "30")
    monkeypatch.setenv("CACHE_MAX_TTL_SECONDS", "2.5")
    settings = Settings.from_env()
    assert settings.base_url == "https://sho.rt"
    assert settings.expiration_seconds == 30
    assert settings.cache_max_ttl_seconds == 2.5


def test_render_url_is_used_when_base_url_is_missing(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://demo.onrender.com")
    assert Settings.from_env().base_url == "https://demo.onrender.com"


@pytest.mark.parametrize("name", ["EXPIRATION_SECONDS", "CACHE_MAX_TTL_SECONDS"])
def test_non_numeric_env_values_are_reported_by_name(monkeypatch, name):
    monkeypatch.setenv(name, "ten")
    with pytest.raises(ConfigurationError, match=name):
        Settings.from_env()
