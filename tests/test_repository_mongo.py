from concurrent.futures import ThreadPoolExecutor

import pytest
from pymongo import MongoClient, monitoring

from app.errors import ShortUrlExpiredError, ShortUrlNotFoundError
from app.repository import ACTIVE_URL_INDEX, CODE_INDEX, RETENTION_INDEX, MongoShortUrlRepository, url_hash
from tests.conftest import BASE_URL, TTL_SECONDS

pytestmark = pytest.mark.integration

LONG_URL = "https://www.example.com/path?q=search"


def test_indexes_are_created(mongo_repo):
    indexes = mongo_repo._col.index_information()
    assert indexes[CODE_INDEX]["unique"]
    assert indexes[ACTIVE_URL_INDEX]["unique"]
    assert indexes[ACTIVE_URL_INDEX]["partialFilterExpression"] == {"active": True}
    assert indexes[RETENTION_INDEX]["expireAfterSeconds"] == 3600


def test_minify_and_expand_roundtrip(mongo_service):
    result = mongo_service.minify(LONG_URL)
    assert result.created
    record = mongo_service.expand(result.short_url)
    assert record.long_url == LONG_URL
    assert record.expires_at == result.record.expires_at


def test_same_url_returns_same_code(mongo_service, clock):
    first = mongo_service.minify(LONG_URL)
    clock.advance(TTL_SECONDS - 1)
    second = mongo_service.minify(LONG_URL)
    assert (second.short_url, second.created) == (first.short_url, False)


def test_expired_url_gets_new_code_and_old_one_stays_expired(mongo_service, mongo_repo, clock):
    old = mongo_service.minify(LONG_URL)
    clock.advance(TTL_SECONDS)
    new = mongo_service.minify(LONG_URL)
    assert new.created and new.short_url != old.short_url
    assert mongo_service.expand(new.short_url).long_url == LONG_URL
    with pytest.raises(ShortUrlExpiredError):
        mongo_service.expand(old.short_url)
    assert mongo_repo._col.count_documents({"long_url": LONG_URL, "active": True}) == 1


def test_unknown_code(mongo_service):
    with pytest.raises(ShortUrlNotFoundError):
        mongo_service.expand(f"{BASE_URL}/missing")


def test_code_collision_is_detected(mongo_repo, clock):
    from app.service import UrlShortenerService

    codes = iter(["dup0000", "dup0000", "ok00000"])
    svc = UrlShortenerService(
        mongo_repo,
        base_url=BASE_URL,
        expiration_seconds=TTL_SECONDS,
        clock=clock,
        code_generator=lambda _length: next(codes),
    )
    assert svc.minify("https://a.example.com/").record.code == "dup0000"
    assert svc.minify("https://b.example.com/").record.code == "ok00000"


def test_concurrent_minify_of_same_url_is_race_free(mongo_service, mongo_repo):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: mongo_service.minify(LONG_URL), range(64)))
    assert len({r.short_url for r in results}) == 1
    assert mongo_repo._col.count_documents({"long_url": LONG_URL}) == 1


class CommandRecorder(monitoring.CommandListener):
    def __init__(self):
        self.commands: list[str] = []

    def started(self, event):
        self.commands.append(event.command_name)

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


def test_reusing_an_active_url_is_a_single_read(mongo_client, mongo_repo, clock):
    from app.service import UrlShortenerService

    recorder = CommandRecorder()
    client = MongoClient(mongo_client.address[0], mongo_client.address[1], tz_aware=True, event_listeners=[recorder])
    repo = MongoShortUrlRepository(client[mongo_repo._col.database.name]["short_urls"], retention_seconds=3600)
    svc = UrlShortenerService(repo, base_url=BASE_URL, expiration_seconds=TTL_SECONDS, clock=clock)
    svc.minify(LONG_URL)
    recorder.commands.clear()
    svc.minify(LONG_URL)
    commands = list(recorder.commands)
    client.close()
    assert commands == ["find"]


def test_documents_are_keyed_by_url_hash(mongo_service, mongo_repo):
    mongo_service.minify(LONG_URL)
    doc = mongo_repo._col.find_one({})
    assert doc["url_hash"] == url_hash(LONG_URL)
    assert doc["long_url"] == LONG_URL
