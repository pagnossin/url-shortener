from datetime import datetime


class ShortenerError(Exception):
    pass


class ConfigurationError(ShortenerError):
    pass


class InvalidUrlError(ShortenerError):
    pass


class InvalidShortUrlError(ShortenerError):
    pass


class ShortUrlNotFoundError(ShortenerError):
    pass


class ShortUrlExpiredError(ShortenerError):
    def __init__(self, message: str, expired_at: datetime):
        super().__init__(message)
        self.expired_at = expired_at


class CodeCollisionError(ShortenerError):
    pass


class CodeGenerationError(ShortenerError):
    pass


class StorageUnavailableError(ShortenerError):
    pass
