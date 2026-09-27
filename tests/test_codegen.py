import pytest

from app.codegen import ALPHABET, generate_code, is_valid_code


def test_generates_code_of_requested_length_from_base62_alphabet():
    code = generate_code(10)
    assert len(code) == 10
    assert set(code) <= set(ALPHABET)


def test_alphabet_is_base62():
    assert len(set(ALPHABET)) == 62


def test_codes_are_random():
    codes = {generate_code(7) for _ in range(10_000)}
    assert len(codes) == 10_000


def test_rejects_non_positive_length():
    with pytest.raises(ValueError):
        generate_code(0)


@pytest.mark.parametrize("code,valid", [("aZ3", True), ("", False), ("ab-c", False), ("a" * 33, False)])
def test_is_valid_code(code, valid):
    assert is_valid_code(code) is valid
