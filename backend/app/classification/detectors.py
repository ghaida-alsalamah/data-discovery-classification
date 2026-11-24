"""Local structural detectors. Validation failures never erase structural hits."""
import re
from datetime import datetime
from typing import NamedTuple

DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PATTERNS = {
    "saudi_national_id": r"1[0-9]{9}",
    "saudi_residency_id": r"2[0-9]{9}",
    "phone_number": r"(?:\+966|00966|966)[0-9]{9}|0[0-9]{9}",
    "saudi_iban": r"SA[0-9]{2}[A-Z0-9]{20}",
    "email_address": r"[^@\s]+@[^@\s]+\.[^@\s]+",
    "date": r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T][0-9]{2}:[0-9]{2}:[0-9]{2})?|[0-9]{2}/[0-9]{2}/[0-9]{4}",
}
COMPILED = {kind: re.compile(pattern, re.ASCII | re.IGNORECASE) for kind, pattern in PATTERNS.items()}
NAME = re.compile(r"(?:[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?(?: [A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?){1,3}|[\u0621-\u064a]{2,}(?: [\u0621-\u064a]{2,}){1,3})")


class Hit(NamedTuple):
    format_valid: bool | None
    checksum_valid: bool | None = None


def normalize(value):
    return str(value).strip().translate(DIGITS)


def id_checksum(value):
    total = sum(sum(divmod(int(digit) * (2 if index % 2 == 0 else 1), 10))
                for index, digit in enumerate(value))
    return total % 10 == 0


def iban_checksum(value):
    remainder = 0
    for char in value[4:] + value[:4]:
        digits = char if char.isdigit() else str(ord(char) - 55)
        remainder = (remainder * 10 ** len(digits) + int(digits)) % 97
    return remainder == 1


def valid_date(value):
    try:
        if "/" in value:
            datetime.strptime(value, "%d/%m/%Y")
        else:
            datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def detect(value):
    text = normalize(value)
    compact = re.sub(r"[\s-]", "", text)
    upper = re.sub(r"\s", "", text).upper()
    hits = {}
    for kind in ("saudi_national_id", "saudi_residency_id"):
        if COMPILED[kind].fullmatch(compact):
            hits[kind] = Hit(compact == text, id_checksum(compact))
    if COMPILED["phone_number"].fullmatch(compact):
        subscriber = compact[-9:]
        hits["phone_number"] = Hit(subscriber[0] in "15")
    if COMPILED["saudi_iban"].fullmatch(upper):
        hits["saudi_iban"] = Hit(2 <= int(upper[2:4]) <= 98 and upper[4:6].isdigit()
                                and upper[4:6] != "00",
                                iban_checksum(upper))
    if COMPILED["email_address"].fullmatch(text):
        local, domain = text.rsplit("@", 1)
        labels = domain.split(".")
        valid = (len(local) <= 64 and len(text) <= 254 and not local.startswith(".")
                 and not local.endswith(".") and ".." not in local
                 and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                         for label in labels) and labels[-1].isalpha())
        hits["email_address"] = Hit(bool(valid))
    if COMPILED["date"].fullmatch(text):
        hits["date"] = Hit(valid_date(text))
    if NAME.fullmatch(text):
        hits["person_name"] = Hit(None)
    return hits


def detection_summary(values):
    counts = {}
    for value in values:
        for kind, hit in detect(value).items():
            entry = counts.setdefault(kind, {
                "structural": 0, "format_valid": 0, "format_invalid": 0,
                "checksum_valid": 0, "checksum_invalid": 0,
            })
            entry["structural"] += 1
            for check, result in zip(("format", "checksum"), hit):
                if result is not None:
                    entry[f"{check}_{'valid' if result else 'invalid'}"] += 1
    for kind, prefix in (("saudi_national_id", "1"), ("saudi_residency_id", "2"),
                         ("phone_number", "966_or_domestic_0"), ("saudi_iban", "SA")):
        if kind in counts:
            counts[kind]["recognized_prefix"] = prefix
    return counts
