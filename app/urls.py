from urllib.parse import urlsplit, urlunsplit

from .codegen import is_valid_code
from .errors import InvalidShortUrlError, InvalidUrlError

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise InvalidUrlError("URL is empty")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidUrlError(f"URL is longer than {MAX_URL_LENGTH} characters")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise InvalidUrlError("URL must not contain whitespace or control characters")

    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        _ = parts.port  # raises on an invalid port
    except ValueError as exc:
        raise InvalidUrlError(f"Malformed URL: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidUrlError("Only http and https URLs are supported")
    if not hostname:
        raise InvalidUrlError("URL must contain a host")
    # e.g. https://bank.com@evil.com
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("URLs with credentials (user:password@) are not accepted")

    # scheme and host are case-insensitive, path and query are not
    return urlunsplit((scheme, parts.netloc.lower(), parts.path or "/", parts.query, parts.fragment))


def extract_code(short_url: str, base_url: str) -> str:
    url = (short_url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise InvalidShortUrlError(f"Malformed short URL: {exc}") from exc
    base = urlsplit(base_url)

    prefix = base.path.rstrip("/") + "/"
    same_origin = (parts.scheme.lower(), parts.netloc.lower()) == (base.scheme.lower(), base.netloc.lower())
    if not same_origin or not parts.path.startswith(prefix) or parts.query or parts.fragment:
        raise InvalidShortUrlError(f"Not a short URL of this service (expected {base_url.rstrip('/')}/<code>)")

    code = parts.path[len(prefix) :].rstrip("/")
    if not is_valid_code(code):
        raise InvalidShortUrlError("Short URL contains an invalid code")
    return code


def same_host(url: str, base_url: str) -> bool:
    return urlsplit(url).netloc.lower() == urlsplit(base_url).netloc.lower()
