import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from .codegen import MAX_CODE_LENGTH
from .errors import ConfigurationError


@dataclass(frozen=True)
class Settings:
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "url_shortener"
    base_url: str = "https://myurlshortener.com"
    expiration_seconds: int = 3600
    code_length: int = 7
    retention_seconds: int = 7 * 24 * 3600
    mongo_timeout_ms: int = 3000
    mongo_max_pool_size: int = 50
    cache_max_entries: int = 10_000
    cache_max_ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        base = urlsplit(self.base_url)
        if base.scheme not in ("http", "https") or not base.hostname:
            raise ConfigurationError(f"BASE_URL must be an absolute http(s) URL, got {self.base_url!r}")
        _require(self.expiration_seconds > 0, "EXPIRATION_SECONDS must be positive")
        _require(4 <= self.code_length <= MAX_CODE_LENGTH, f"CODE_LENGTH must be between 4 and {MAX_CODE_LENGTH}")
        _require(self.retention_seconds >= 0, "RETENTION_SECONDS must not be negative")
        _require(self.mongo_timeout_ms > 0, "MONGO_TIMEOUT_MS must be positive")
        _require(self.mongo_max_pool_size > 0, "MONGO_MAX_POOL_SIZE must be positive")
        _require(self.cache_max_entries >= 0, "CACHE_MAX_ENTRIES must not be negative")
        _require(self.cache_max_ttl_seconds >= 0, "CACHE_MAX_TTL_SECONDS must not be negative")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mongo_uri=os.getenv("MONGO_URI", cls.mongo_uri),
            mongo_db=os.getenv("MONGO_DB", cls.mongo_db),
            # on Render the demo points short URLs at itself
            base_url=(os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or cls.base_url).rstrip("/"),
            expiration_seconds=_int_env("EXPIRATION_SECONDS", cls.expiration_seconds),
            code_length=_int_env("CODE_LENGTH", cls.code_length),
            retention_seconds=_int_env("RETENTION_SECONDS", cls.retention_seconds),
            mongo_timeout_ms=_int_env("MONGO_TIMEOUT_MS", cls.mongo_timeout_ms),
            mongo_max_pool_size=_int_env("MONGO_MAX_POOL_SIZE", cls.mongo_max_pool_size),
            cache_max_entries=_int_env("CACHE_MAX_ENTRIES", cls.cache_max_entries),
            cache_max_ttl_seconds=_float_env("CACHE_MAX_TTL_SECONDS", cls.cache_max_ttl_seconds),
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigurationError(message)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from None


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from None
