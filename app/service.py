from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .cache import TTLCache
from .codegen import generate_code, is_valid_code
from .errors import (
    CodeCollisionError,
    CodeGenerationError,
    InvalidUrlError,
    ShortUrlExpiredError,
    ShortUrlNotFoundError,
)
from .repository import ShortUrl, ShortUrlRepository
from .urls import extract_code, normalize_url, same_host

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    # mongo keeps milliseconds only; truncate so stored and in-memory values compare equal
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


@dataclass(frozen=True)
class MinifyResult:
    short_url: str
    record: ShortUrl
    created: bool


class UrlShortenerService:
    def __init__(
        self,
        repository: ShortUrlRepository,
        *,
        base_url: str,
        expiration_seconds: int,
        code_length: int = 7,
        clock: Clock = utc_now,
        code_generator: Callable[[int], str] = generate_code,
        max_attempts: int = 5,
        cache: TTLCache[ShortUrl] | None = None,
        cache_max_ttl_seconds: float = 60.0,
    ):
        if expiration_seconds <= 0:
            raise ValueError("expiration_seconds must be positive")
        self._repo = repository
        self._base_url = base_url.rstrip("/")
        self._ttl = timedelta(seconds=expiration_seconds)
        self._code_length = code_length
        self._clock = clock
        self._generate = code_generator
        self._max_attempts = max_attempts
        self._cache = cache
        self._cache_max_ttl = cache_max_ttl_seconds

    def minify(self, long_url: str) -> MinifyResult:
        normalized = normalize_url(long_url)
        if same_host(normalized, self._base_url):
            raise InvalidUrlError("URL is already a short URL of this service")

        now = self._clock()
        for _ in range(self._max_attempts):
            candidate = ShortUrl(
                code=self._generate(self._code_length),
                long_url=normalized,
                created_at=now,
                expires_at=now + self._ttl,
            )
            try:
                record, created = self._repo.get_or_create_active(candidate, now)
            except CodeCollisionError:
                continue
            return MinifyResult(short_url=self.short_url_for(record.code), record=record, created=created)
        raise CodeGenerationError(f"Could not generate a unique code after {self._max_attempts} attempts")

    def expand(self, short_url: str) -> ShortUrl:
        return self.resolve_code(extract_code(short_url, self._base_url))

    def resolve_code(self, code: str) -> ShortUrl:
        if not is_valid_code(code):
            # /favicon.ico, /wp-admin and friends: no need to ask the database
            raise ShortUrlNotFoundError("Short URL not found")

        now = self._clock()
        record = self._cache.get(code) if self._cache is not None else None
        if record is None:
            record = self._repo.find_by_code(code)
            if record is None:
                raise ShortUrlNotFoundError("Short URL not found")
            if self._cache is not None:
                remaining = (record.expires_at - now).total_seconds()
                self._cache.put(code, record, min(remaining, self._cache_max_ttl))

        if record.is_expired(now):
            raise ShortUrlExpiredError(
                f"Short URL expired at {record.expires_at.isoformat()}", expired_at=record.expires_at
            )
        return record

    def seconds_to_expiry(self, record: ShortUrl) -> int:
        return max(0, int((record.expires_at - self._clock()).total_seconds()))

    def short_url_for(self, code: str) -> str:
        return f"{self._base_url}/{code}"
