import pytest

from app.errors import InvalidShortUrlError, InvalidUrlError
from app.urls import extract_code, normalize_url

BASE = "https://myurlshortener.com"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.example.com/path?q=search", "https://www.example.com/path?q=search"),
        ("  HTTPS://WWW.Example.COM/Path?Q=1  ", "https://www.example.com/Path?Q=1"),
        ("http://example.com", "http://example.com/"),
        ("https://example.com:8443/a#frag", "https://example.com:8443/a#frag"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "example.com",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://",
        "https://exa mple.com",
        "https://example.com:99999/",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_normalize_rejects_invalid_urls(raw):
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)


@pytest.mark.parametrize(
    "short,code",
    [
        ("https://myurlshortener.com/fstp4", "fstp4"),
        ("https://MyUrlShortener.com/fstp4/", "fstp4"),
        (" https://myurlshortener.com/AbC123 ", "AbC123"),
    ],
)
def test_extract_code(short, code):
    assert extract_code(short, BASE) == code


def test_extract_code_supports_base_url_with_path():
    assert extract_code("https://example.com/s/abc", "https://example.com/s") == "abc"


@pytest.mark.parametrize(
    "short",
    [
        "https://other.com/fstp4",
        "http://myurlshortener.com/fstp4",
        "https://myurlshortener.com/",
        "https://myurlshortener.com/a/b",
        "https://myurlshortener.com/fs-tp4",
        "https://myurlshortener.com/fstp4?x=1",
        "fstp4",
    ],
)
def test_extract_code_rejects_foreign_or_malformed_short_urls(short):
    with pytest.raises(InvalidShortUrlError):
        extract_code(short, BASE)


@pytest.mark.parametrize(
    "raw",
    [
        "https://bank.com@evil.com/login",  # phishing: the real host is evil.com
        "https://user:secret@example.com/",
        "https://example.com/\x00admin",
        "https://example.com/a\x7f",
        "https://example.com/\tpath",
    ],
)
def test_normalize_rejects_credentials_and_control_characters(raw):
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)
