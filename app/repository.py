import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from .errors import CodeCollisionError

CODE_INDEX = "uniq_code"
ACTIVE_URL_INDEX = "uniq_active_url_hash"
RETENTION_INDEX = "ttl_retention"


@dataclass(frozen=True)
class ShortUrl:
    code: str
    long_url: str
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class ShortUrlRepository(Protocol):
    def get_or_create_active(self, candidate: ShortUrl, now: datetime) -> tuple[ShortUrl, bool]: ...

    def find_by_code(self, code: str) -> ShortUrl | None: ...


def url_hash(long_url: str) -> str:
    return hashlib.sha256(long_url.encode()).hexdigest()


class MongoShortUrlRepository:
    def __init__(self, collection: Collection[dict[str, Any]], retention_seconds: int):
        self._col = collection
        self._retention_seconds = retention_seconds

    def ensure_indexes(self) -> None:
        self._col.create_index("code", unique=True, name=CODE_INDEX)
        # at most one active record per url; expired ones stay around as inactive
        self._col.create_index(
            "url_hash",
            unique=True,
            partialFilterExpression={"active": True},
            name=ACTIVE_URL_INDEX,
        )
        self._col.create_index("expires_at", expireAfterSeconds=self._retention_seconds, name=RETENTION_INDEX)

    def get_or_create_active(self, candidate: ShortUrl, now: datetime) -> tuple[ShortUrl, bool]:
        active = {"url_hash": url_hash(candidate.long_url), "active": True}

        doc = self._col.find_one(active)
        if doc is not None:
            existing = _to_short_url(doc)
            if not existing.is_expired(now):
                return existing, False
            self._col.update_one({"_id": doc["_id"], "active": True}, {"$set": {"active": False}})

        try:
            doc = self._col.find_one_and_update(
                active,
                {
                    "$setOnInsert": {
                        "code": candidate.code,
                        "long_url": candidate.long_url,
                        "created_at": candidate.created_at,
                        "expires_at": candidate.expires_at,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            if _violated_index(exc) == CODE_INDEX:
                raise CodeCollisionError(candidate.code) from exc
            # another request created the active record first: use that one
            doc = self._col.find_one(active)
        if doc is None:  # pragma: no cover
            raise CodeCollisionError(candidate.code)

        record = _to_short_url(doc)
        return record, record.code == candidate.code

    def find_by_code(self, code: str) -> ShortUrl | None:
        doc = self._col.find_one({"code": code}, projection={"_id": False, "url_hash": False, "active": False})
        return _to_short_url(doc) if doc else None


def _violated_index(exc: DuplicateKeyError) -> str | None:
    details = exc.details or {}
    key_pattern = details.get("keyPattern") or {}
    message = str(details.get("errmsg", ""))
    if "code" in key_pattern or CODE_INDEX in message:
        return CODE_INDEX
    if "url_hash" in key_pattern or ACTIVE_URL_INDEX in message:
        return ACTIVE_URL_INDEX
    return None


def _to_short_url(doc: dict[str, Any]) -> ShortUrl:
    return ShortUrl(
        code=doc["code"],
        long_url=doc["long_url"],
        created_at=doc["created_at"],
        expires_at=doc["expires_at"],
    )


class InMemoryShortUrlRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_code: dict[str, ShortUrl] = {}
        self._active: dict[str, str] = {}
        self.reads = 0

    def get_or_create_active(self, candidate: ShortUrl, now: datetime) -> tuple[ShortUrl, bool]:
        with self._lock:
            code = self._active.get(candidate.long_url)
            if code is not None:
                existing = self._by_code[code]
                if not existing.is_expired(now):
                    return existing, False
                del self._active[candidate.long_url]
            if candidate.code in self._by_code:
                raise CodeCollisionError(candidate.code)
            self._by_code[candidate.code] = candidate
            self._active[candidate.long_url] = candidate.code
            return candidate, True

    def find_by_code(self, code: str) -> ShortUrl | None:
        with self._lock:
            self.reads += 1
            return self._by_code.get(code)
