import re

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SHAPE = re.compile(r"^(0[1-9]|[12]\d|3[0-8]|97|99)[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def check_char(first14: str) -> str:
    """The GSTIN check character: a Luhn-style mod-36 checksum over the first 14 characters."""
    total = 0
    for i, ch in enumerate(first14):
        product = _ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(value: str) -> bool:
    value = value.upper()
    return bool(_SHAPE.match(value)) and check_char(value[:14]) == value[14]


def validate_gstin(value: str | None) -> str | None:
    """Pydantic validator: None passes, anything else must be a real GSTIN."""
    if value is None or value == "":
        return None
    if not is_valid_gstin(value):
        raise ValueError("Not a valid GSTIN (check the characters and the last check digit)")
    return value.upper()
