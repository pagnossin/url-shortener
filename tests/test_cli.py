import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.cli import EXIT_CONFIGURATION, EXIT_INVALID_INPUT, EXIT_NOT_FOUND, EXIT_OK, EXIT_STORAGE_UNAVAILABLE, main
from app.errors import ConfigurationError
from tests.conftest import BASE_URL, TTL_SECONDS

LONG_URL = "https://www.example.com/path?q=search"


def run(service, capsys, *argv):
    code = main(list(argv), service_factory=lambda: service)
    out, err = capsys.readouterr()
    return code, out.strip(), err.strip()


def test_minify_prints_short_url(service, capsys):
    code, out, err = run(service, capsys, f"--minify={LONG_URL}")
    assert code == EXIT_OK
    assert out.startswith(f"{BASE_URL}/")
    assert err == ""


def test_minify_twice_prints_same_short_url(service, capsys):
    _, first, _ = run(service, capsys, f"--minify={LONG_URL}")
    _, second, _ = run(service, capsys, "--minify", LONG_URL)
    assert first == second


def test_expand_prints_original_url(service, capsys):
    _, short_url, _ = run(service, capsys, f"--minify={LONG_URL}")
    code, out, _ = run(service, capsys, f"--expand={short_url}")
    assert code == EXIT_OK
    assert out == LONG_URL


def test_expand_unknown_prints_message(service, capsys):
    code, out, err = run(service, capsys, f"--expand={BASE_URL}/unknown")
    assert code == EXIT_NOT_FOUND
    assert out == ""
    assert "not found" in err


def test_expand_expired_prints_message(service, clock, capsys):
    _, short_url, _ = run(service, capsys, f"--minify={LONG_URL}")
    clock.advance(TTL_SECONDS)
    code, _, err = run(service, capsys, f"--expand={short_url}")
    assert code == EXIT_NOT_FOUND
    assert "expired" in err


def test_invalid_url_prints_message(service, capsys):
    code, _, err = run(service, capsys, "--minify=ftp://example.com")
    assert code == EXIT_INVALID_INPUT
    assert "Invalid input" in err


def test_storage_unavailable(capsys):
    def failing_factory():
        raise ServerSelectionTimeoutError("no servers")

    code = main([f"--minify={LONG_URL}"], service_factory=failing_factory)
    assert code == EXIT_STORAGE_UNAVAILABLE
    assert "Storage unavailable" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], [f"--minify={LONG_URL}", f"--expand={BASE_URL}/abc"]])
def test_requires_exactly_one_action(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv, service_factory=lambda: None)
    assert exc.value.code == 2


def test_configuration_error(capsys):
    def bad_config():
        raise ConfigurationError("EXPIRATION_SECONDS must be positive")

    assert main([f"--minify={LONG_URL}"], service_factory=bad_config) == EXIT_CONFIGURATION
    assert "Configuration error: EXPIRATION_SECONDS" in capsys.readouterr().err
