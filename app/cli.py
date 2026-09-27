import argparse
import sys
from collections.abc import Callable, Sequence

from pymongo.errors import PyMongoError

from .bootstrap import build_service
from .config import Settings
from .errors import (
    ConfigurationError,
    InvalidShortUrlError,
    InvalidUrlError,
    ShortenerError,
    ShortUrlExpiredError,
    ShortUrlNotFoundError,
    StorageUnavailableError,
)
from .service import UrlShortenerService

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_INVALID_INPUT = 2
EXIT_STORAGE_UNAVAILABLE = 3
EXIT_CONFIGURATION = 4

ServiceFactory = Callable[[], UrlShortenerService]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Shorten and expand URLs.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--minify", metavar="URL", help="return the short URL for URL")
    action.add_argument("--expand", metavar="SHORT_URL", help="return the original URL behind SHORT_URL")
    return parser


def main(argv: Sequence[str] | None = None, service_factory: ServiceFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    service_factory = service_factory or (lambda: build_service(Settings.from_env()))

    try:
        service = service_factory()
        if args.minify is not None:
            print(service.minify(args.minify).short_url)
        else:
            print(service.expand(args.expand).long_url)
        return EXIT_OK
    except (InvalidUrlError, InvalidShortUrlError) as exc:
        return _fail(f"Invalid input: {exc}", EXIT_INVALID_INPUT)
    except ShortUrlNotFoundError:
        return _fail("Short URL not found.", EXIT_NOT_FOUND)
    except ShortUrlExpiredError as exc:
        return _fail(f"Short URL has expired ({exc.expired_at:%Y-%m-%d %H:%M:%S} UTC).", EXIT_NOT_FOUND)
    except ConfigurationError as exc:
        return _fail(f"Configuration error: {exc}", EXIT_CONFIGURATION)
    except StorageUnavailableError as exc:
        return _fail(f"Storage unavailable: {exc}", EXIT_STORAGE_UNAVAILABLE)
    except PyMongoError as exc:
        return _fail(f"Storage unavailable: MongoDB error ({type(exc).__name__})", EXIT_STORAGE_UNAVAILABLE)
    except ShortenerError as exc:
        return _fail(f"Error: {exc}", EXIT_STORAGE_UNAVAILABLE)


def _fail(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code
