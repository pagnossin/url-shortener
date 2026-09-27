import secrets
import string

ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
MAX_CODE_LENGTH = 32

_ALPHABET_SET = frozenset(ALPHABET)


def generate_code(length: int = 7) -> str:
    # random rather than sequential: codes can't be enumerated and no shared counter is needed
    if length < 1:
        raise ValueError("length must be positive")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_valid_code(code: str, max_length: int = MAX_CODE_LENGTH) -> bool:
    return 0 < len(code) <= max_length and all(c in _ALPHABET_SET for c in code)
