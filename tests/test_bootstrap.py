import json
import logging

import pytest

from app.bootstrap import build_service
from app.config import Settings
from app.errors import StorageUnavailableError
from app.observability import JsonFormatter
from app.service import utc_now
from tests.conftest import BASE_URL


def test_build_service_creates_indexes_and_cache(mongo_client):
    settings = Settings(mongo_db="url_shortener_bootstrap_test", base_url=BASE_URL)
    try:
        service = build_service(settings, mongo_client, with_cache=True)
        result = service.minify("https://www.example.com/")
        assert service.expand(result.short_url).long_url == "https://www.example.com/"
        assert service._cache is not None
    finally:
        mongo_client.drop_database(settings.mongo_db)


def test_unreachable_mongodb_is_reported_without_the_connection_string():
    settings = Settings(mongo_uri="mongodb://user:secret@127.0.0.1:1", mongo_timeout_ms=300)
    with pytest.raises(StorageUnavailableError) as exc:
        build_service(settings)
    assert "secret" not in str(exc.value)


def test_json_log_lines():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "request", None, None)
    record.fields = {"status": 200, "path": "/abc"}
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "request" and line["status"] == 200 and line["level"] == "INFO"


def test_utc_now_has_millisecond_precision_like_mongodb():
    assert utc_now().microsecond % 1000 == 0
