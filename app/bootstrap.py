from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .cache import TTLCache
from .config import Settings
from .errors import StorageUnavailableError
from .repository import MongoShortUrlRepository, ShortUrl
from .service import UrlShortenerService

COLLECTION = "short_urls"


def create_mongo_client(settings: Settings) -> MongoClient[dict[str, Any]]:
    return MongoClient(
        settings.mongo_uri,
        tz_aware=True,
        appname="url-shortener",
        timeoutMS=settings.mongo_timeout_ms,
        connectTimeoutMS=settings.mongo_timeout_ms,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
        maxPoolSize=settings.mongo_max_pool_size,
        w="majority",
        retryWrites=True,
        retryReads=True,
    )


def build_service(
    settings: Settings,
    client: MongoClient[dict[str, Any]] | None = None,
    *,
    with_cache: bool = False,
) -> UrlShortenerService:
    client = client or create_mongo_client(settings)
    repository = MongoShortUrlRepository(client[settings.mongo_db][COLLECTION], settings.retention_seconds)
    try:
        repository.ensure_indexes()
    except PyMongoError as exc:
        # the driver message can contain the connection string
        raise StorageUnavailableError(f"MongoDB is not reachable ({type(exc).__name__})") from exc

    cache: TTLCache[ShortUrl] | None = None
    if with_cache and settings.cache_max_entries > 0:
        cache = TTLCache(settings.cache_max_entries)

    return UrlShortenerService(
        repository,
        base_url=settings.base_url,
        expiration_seconds=settings.expiration_seconds,
        code_length=settings.code_length,
        cache=cache,
        cache_max_ttl_seconds=settings.cache_max_ttl_seconds,
    )
