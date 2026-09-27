import pytest

from app.cache import TTLCache


class Ticker:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_returns_value_until_its_ttl():
    clock = Ticker()
    cache: TTLCache[str] = TTLCache(10, clock=clock)
    cache.put("a", "x", ttl_seconds=5)
    clock.now = 4.9
    assert cache.get("a") == "x"
    clock.now = 5
    assert cache.get("a") is None
    assert len(cache) == 0  # expired entries are dropped on access


def test_evicts_least_recently_used_beyond_capacity():
    cache: TTLCache[int] = TTLCache(2)
    cache.put("a", 1, 60)
    cache.put("b", 2, 60)
    cache.get("a")  # "a" becomes the most recently used
    cache.put("c", 3, 60)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_non_positive_ttl_is_not_stored():
    cache: TTLCache[int] = TTLCache(2)
    cache.put("a", 1, 0)
    cache.put("b", 1, -5)
    assert len(cache) == 0


def test_rejects_invalid_capacity():
    with pytest.raises(ValueError):
        TTLCache(0)
