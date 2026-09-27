import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.repository import InMemoryShortUrlRepository, MongoShortUrlRepository
from app.service import UrlShortenerService

BASE_URL = "https://myurlshortener.com"
TTL_SECONDS = 60


class FakeClock:
    def __init__(self, start: datetime = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def memory_repo() -> InMemoryShortUrlRepository:
    return InMemoryShortUrlRepository()


@pytest.fixture
def service(memory_repo, clock) -> UrlShortenerService:
    return UrlShortenerService(memory_repo, base_url=BASE_URL, expiration_seconds=TTL_SECONDS, clock=clock)


@pytest.fixture(scope="session")
def mongo_client():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        if os.getenv("REQUIRE_MONGO"):
            pytest.fail(f"MongoDB not reachable at {uri}")
        pytest.skip(f"MongoDB not reachable at {uri}")
    yield client
    client.close()


@pytest.fixture
def mongo_repo(mongo_client):
    db_name = f"url_shortener_test_{uuid.uuid4().hex[:8]}"
    repo = MongoShortUrlRepository(mongo_client[db_name]["short_urls"], retention_seconds=3600)
    repo.ensure_indexes()
    yield repo
    mongo_client.drop_database(db_name)


@pytest.fixture
def mongo_service(mongo_repo, clock) -> UrlShortenerService:
    return UrlShortenerService(mongo_repo, base_url=BASE_URL, expiration_seconds=TTL_SECONDS, clock=clock)
