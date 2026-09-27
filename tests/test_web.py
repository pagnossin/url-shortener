import pytest
from fastapi.testclient import TestClient
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError

from app.web import create_app
from tests.conftest import BASE_URL, TTL_SECONDS

LONG_URL = "https://www.example.com/path?q=search"


@pytest.fixture
def client(service):
    with TestClient(create_app(lambda: service)) as c:
        yield c


def test_minify_creates_then_reuses(client):
    first = client.post("/api/minify", json={"url": LONG_URL})
    second = client.post("/api/minify", json={"url": LONG_URL})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["short_url"] == second.json()["short_url"]
    assert first.json()["short_url"].startswith(BASE_URL)


def test_minify_invalid_url_returns_400(client):
    assert client.post("/api/minify", json={"url": "nope"}).status_code == 400


def test_expand(client):
    short_url = client.post("/api/minify", json={"url": LONG_URL}).json()["short_url"]
    res = client.get("/api/expand", params={"short_url": short_url})
    assert res.status_code == 200
    assert res.json()["long_url"] == LONG_URL


def test_expand_unknown_returns_404(client):
    assert client.get("/api/expand", params={"short_url": f"{BASE_URL}/zzz"}).status_code == 404


def test_expand_expired_returns_410(client, clock):
    short_url = client.post("/api/minify", json={"url": LONG_URL}).json()["short_url"]
    clock.advance(TTL_SECONDS)
    assert client.get("/api/expand", params={"short_url": short_url}).status_code == 410


def test_redirect(client):
    code = client.post("/api/minify", json={"url": LONG_URL}).json()["code"]
    res = client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == LONG_URL


def test_index_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_liveness_does_not_depend_on_mongodb_but_readiness_does(client):
    def ping():
        raise ServerSelectionTimeoutError("down")

    client.app.state.ping = ping
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_redirect_is_cacheable_but_never_beyond_expiry(client, clock):
    code = client.post("/api/minify", json={"url": LONG_URL}).json()["code"]
    clock.advance(TTL_SECONDS - 10)
    res = client.get(f"/{code}", follow_redirects=False)
    assert res.headers["cache-control"] == "public, max-age=10"


def test_expired_and_unknown_responses_cache_policy(client, clock):
    code = client.post("/api/minify", json={"url": LONG_URL}).json()["code"]
    assert client.get("/zzzzzzz").headers["cache-control"] == "no-store"
    clock.advance(TTL_SECONDS)
    res = client.get(f"/{code}")
    assert res.status_code == 410
    assert res.headers["cache-control"] == "public, max-age=3600"


def test_every_response_has_request_id_and_security_headers(client):
    res = client.get("/healthz")
    assert len(res.headers["x-request-id"]) == 32
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    forwarded = client.get("/healthz", headers={"X-Request-ID": "lb-abc-123"})
    assert forwarded.headers["x-request-id"] == "lb-abc-123"
    unsafe = client.get("/healthz", headers={"X-Request-ID": "bad<id>"})
    assert unsafe.headers["x-request-id"] != "bad<id>"


def test_database_errors_become_503_without_leaking_details(client, service, monkeypatch):
    def failing(_url):
        raise AutoReconnect("primary stepped down, mongodb://user:secret@db")

    monkeypatch.setattr(service, "minify", failing)
    res = client.post("/api/minify", json={"url": LONG_URL})
    assert res.status_code == 503
    assert res.headers["retry-after"] == "2"
    assert "secret" not in res.text


def test_oversized_request_is_rejected(client):
    assert client.post("/api/minify", json={"url": "https://a.com/" + "x" * 5000}).status_code == 422
