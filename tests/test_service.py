from concurrent.futures import ThreadPoolExecutor

import pytest

from app.cache import TTLCache
from app.errors import (
    CodeGenerationError,
    InvalidShortUrlError,
    InvalidUrlError,
    ShortUrlExpiredError,
    ShortUrlNotFoundError,
)
from app.service import UrlShortenerService
from tests.conftest import BASE_URL, TTL_SECONDS

LONG_URL = "https://www.example.com/path?q=search"


def test_minify_returns_short_url_on_base_url(service):
    result = service.minify(LONG_URL)
    assert result.created
    assert result.short_url == f"{BASE_URL}/{result.record.code}"
    assert result.record.long_url == LONG_URL


def test_minify_sets_expiration(service, clock):
    result = service.minify(LONG_URL)
    assert (result.record.expires_at - clock.now).total_seconds() == TTL_SECONDS


def test_minify_same_url_returns_same_short_url_while_not_expired(service, clock):
    first = service.minify(LONG_URL)
    clock.advance(TTL_SECONDS - 1)
    second = service.minify(LONG_URL)
    assert second.short_url == first.short_url
    assert not second.created


def test_minify_equivalent_urls_share_the_short_url(service):
    assert service.minify("HTTPS://WWW.EXAMPLE.COM/path?q=search").short_url == service.minify(LONG_URL).short_url


def test_different_urls_get_different_short_urls(service):
    assert service.minify(LONG_URL).short_url != service.minify("https://www.example.com/other").short_url


def test_expired_url_can_be_minified_again_with_a_new_code(service, clock):
    first = service.minify(LONG_URL)
    clock.advance(TTL_SECONDS)
    second = service.minify(LONG_URL)
    assert second.created
    assert second.short_url != first.short_url
    assert service.expand(second.short_url).long_url == LONG_URL


def test_expand_returns_original_url(service):
    short_url = service.minify(LONG_URL).short_url
    assert service.expand(short_url).long_url == LONG_URL


def test_expand_just_before_expiration(service, clock):
    short_url = service.minify(LONG_URL).short_url
    clock.advance(TTL_SECONDS - 0.001)
    assert service.expand(short_url).long_url == LONG_URL


def test_expand_expired_url_raises_expired(service, clock):
    short_url = service.minify(LONG_URL).short_url
    clock.advance(TTL_SECONDS)
    with pytest.raises(ShortUrlExpiredError):
        service.expand(short_url)


def test_old_code_stays_expired_after_url_is_minified_again(service, clock):
    old = service.minify(LONG_URL).short_url
    clock.advance(TTL_SECONDS + 1)
    service.minify(LONG_URL)
    with pytest.raises(ShortUrlExpiredError):
        service.expand(old)


def test_expand_unknown_code_raises_not_found(service):
    with pytest.raises(ShortUrlNotFoundError):
        service.expand(f"{BASE_URL}/nope123")


def test_expand_foreign_url_raises_invalid(service):
    with pytest.raises(InvalidShortUrlError):
        service.expand("https://bit.ly/abc")


def test_minify_invalid_url_raises_invalid(service):
    with pytest.raises(InvalidUrlError):
        service.minify("not a url")


def test_code_collision_is_retried(memory_repo, clock):
    codes = iter(["taken00", "taken00", "fresh00"])
    svc = UrlShortenerService(
        memory_repo,
        base_url=BASE_URL,
        expiration_seconds=TTL_SECONDS,
        clock=clock,
        code_generator=lambda _length: next(codes),
    )
    assert svc.minify("https://a.example.com/").record.code == "taken00"
    assert svc.minify("https://b.example.com/").record.code == "fresh00"


def test_gives_up_after_max_attempts(memory_repo, clock):
    svc = UrlShortenerService(
        memory_repo,
        base_url=BASE_URL,
        expiration_seconds=TTL_SECONDS,
        clock=clock,
        code_generator=lambda _length: "always0",
        max_attempts=3,
    )
    svc.minify("https://a.example.com/")
    with pytest.raises(CodeGenerationError):
        svc.minify("https://b.example.com/")


def test_concurrent_minify_of_same_url_returns_one_short_url(service):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: service.minify(LONG_URL), range(64)))
    assert len({r.short_url for r in results}) == 1
    assert sum(r.created for r in results) == 1


def test_rejects_non_positive_expiration(memory_repo):
    with pytest.raises(ValueError):
        UrlShortenerService(memory_repo, base_url=BASE_URL, expiration_seconds=0)


def test_minify_refuses_urls_of_the_shortener_itself(service):
    with pytest.raises(InvalidUrlError, match="already a short URL"):
        service.minify(f"{BASE_URL}/abc1234")


@pytest.mark.parametrize("path", ["favicon.ico", "wp-admin", "a" * 40, ""])
def test_impossible_codes_never_reach_the_database(service, memory_repo, path):
    with pytest.raises(ShortUrlNotFoundError):
        service.resolve_code(path)
    assert memory_repo.reads == 0


class Ticker:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def cached_service(memory_repo, clock, ticker, max_ttl=60.0):
    return UrlShortenerService(
        memory_repo,
        base_url=BASE_URL,
        expiration_seconds=TTL_SECONDS,
        clock=clock,
        cache=TTLCache(100, clock=ticker),
        cache_max_ttl_seconds=max_ttl,
    )


def test_cache_serves_hot_codes_without_database_reads(memory_repo, clock):
    svc = cached_service(memory_repo, clock, Ticker())
    code = svc.minify(LONG_URL).record.code
    for _ in range(100):
        assert svc.resolve_code(code).long_url == LONG_URL
    assert memory_repo.reads == 1


def test_cached_code_still_expires_exactly_on_time(memory_repo, clock):
    ticker = Ticker()
    svc = cached_service(memory_repo, clock, ticker, max_ttl=3600)
    code = svc.minify(LONG_URL).record.code
    svc.resolve_code(code)  # now cached
    clock.advance(TTL_SECONDS)
    ticker.now += TTL_SECONDS
    with pytest.raises(ShortUrlExpiredError):
        svc.resolve_code(code)


def test_cache_entry_lives_at_most_max_ttl(memory_repo, clock):
    ticker = Ticker()
    svc = cached_service(memory_repo, clock, ticker, max_ttl=5)
    code = svc.minify(LONG_URL).record.code
    svc.resolve_code(code)
    ticker.now = 5
    svc.resolve_code(code)
    assert memory_repo.reads == 2
