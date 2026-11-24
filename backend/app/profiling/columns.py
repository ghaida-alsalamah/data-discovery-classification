import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from numbers import Real

import pandas as pd
from sqlalchemy import MetaData, Table, distinct, func, select, type_coerce
from sqlalchemy.types import NullType

from backend.app.classification.detectors import detection_summary

ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
ENGLISH = re.compile(r"[A-Za-z]")
DATE_FORMATS = (
    (re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}"), "%Y-%m-%d"),
    (re.compile(r"[0-9]{2}/[0-9]{2}/[0-9]{4}"), "%d/%m/%Y"),
)
SAFE_PUNCTUATION = frozenset("@.+-_/():")


def structural_pattern(value):
    symbols = []
    for char in value[:128]:
        if char.isdecimal():
            symbol = "9"
        elif char.isalpha():
            symbol = "A" if ARABIC.fullmatch(char) else "X"
        elif char.isspace():
            symbol = " "
        else:
            symbol = char if char in SAFE_PUNCTUATION else "?"
        symbols.append(symbol)
    return "".join(symbols) + ("…" if len(value) > 128 else "")


def date_format(value):
    if isinstance(value, date):
        return "%Y-%m-%d"
    for pattern, fmt in DATE_FORMATS:
        if pattern.fullmatch(value):
            try:
                datetime.strptime(value, fmt)
            except ValueError:
                continue
            return fmt
    return None


def numeric_statistics(values):
    numeric = []
    for value in values:
        if isinstance(value, (Real, Decimal)) and not isinstance(value, bool):
            try:
                number = float(value)
            except (OverflowError, ValueError):
                continue
            if math.isfinite(number):
                numeric.append(number)
    if len(set(numeric)) < 2:
        return None
    series = pd.Series(numeric, dtype="float64")
    return {
        "count": len(numeric),
        **{name: float(value) if math.isfinite(value) else None for name, value in {
            "mean": series.mean(), "stddev": series.std(ddof=0),
        }.items()},
    }


def sample_values(connection, table, column, non_null, sample_size):
    # Keep source values inside the database until the sample is selected.
    raw = type_coerce(column, NullType())
    order = list(table.primary_key.columns) or [column]
    source = select(raw.label("sample_value")).where(column.is_not(None))
    if non_null <= sample_size:
        return list(connection.scalars(source.order_by(*order)))
    rank = func.row_number().over(order_by=order).label("sample_rank")
    ranked = source.add_columns(rank).subquery()
    index = ranked.c.sample_rank - 1
    # One deterministically jittered rank in each stratum avoids periodic sampling bias.
    bucket = index * sample_size // non_null
    start = (bucket * non_null + sample_size - 1) // sample_size
    end = ((bucket + 1) * non_null + sample_size - 1) // sample_size
    jitter = (bucket * 1103515245 + 12344) % 2147483647
    selected = index == start + jitter % (end - start)
    return list(connection.scalars(
        select(ranked.c.sample_value).where(selected).order_by(ranked.c.sample_rank)
    ))


CURRENCIES = frozenset("SAR AED BHD KWD OMR QAR USD EUR GBP JPY INR CNY EGP JOD CHF CAD AUD".split())
CODE = re.compile(r"[A-Za-z]{1,10}[-_]?[0-9]{1,12}")


def value_indicators(values, strings):
    numeric = [value for value in values if isinstance(value, (Real, Decimal))
               and not isinstance(value, bool)]
    return {
        "numeric": len(numeric),
        "binary": sum(str(value).casefold() in {"0", "1", "true", "false"} for value in values),
        "negative": sum(value.is_signed() and not value.is_zero() and value.is_finite()
                        if isinstance(value, Decimal) else value < 0 for value in numeric),
        "currency": sum(value.strip().upper() in CURRENCIES for value in strings),
        "code": sum(bool(CODE.fullmatch(value.strip())) for value in strings),
    }


def normalization_indicators(values):
    groups = defaultdict(Counter)
    text_count = 0
    for value in values:
        if isinstance(value, str):
            text_count += 1
            normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
            groups[normalized][value] += 1
    variants = [counts for counts in groups.values() if len(counts) > 1]
    return {"text_count": text_count, "variant_groups": len(variants),
            "affected_count": sum(sum(counts.values()) - max(counts.values()) for counts in variants)}


def profile_column(connection, table, column, sample_size=500, presidio=None):
    if type(sample_size) is not int or sample_size < 1:
        raise ValueError("sample_size must be a positive integer")
    total, non_null, distinct_count = connection.execute(
        select(func.count(), func.count(column), func.count(distinct(column))).select_from(table)
    ).one()
    values = sample_values(connection, table, column, non_null, sample_size)
    local_detection = detection_summary(values)
    identifier_kinds = {"saudi_national_id", "saudi_residency_id", "phone_number", "saudi_iban"}
    has_identifier_pattern = any(
        local_detection.get(kind, {}).get("structural", 0) for kind in identifier_kinds
    )

    strings = [str(value) for value in values]
    lengths = [len(value) for value in strings]
    patterns = Counter(map(structural_pattern, strings))
    composition = Counter(dict(letters=0, digits=0, whitespace=0, other=0))
    dates = Counter()
    for value in strings:
        for char in value:
            if char.isalpha():
                composition["letters"] += 1
            elif char.isdecimal():
                composition["digits"] += 1
            elif char.isspace():
                composition["whitespace"] += 1
            else:
                composition["other"] += 1
        fmt = date_format(value)
        if fmt:
            dates[fmt] += 1

    return {
        "total_count": total, "non_null_count": non_null,
        "null_percentage": 100 * (total - non_null) / total if total else 0.0,
        "distinct_count": distinct_count,
        "uniqueness_ratio": distinct_count / non_null if non_null else 0.0,
        "duplicate_count": non_null - distinct_count,
        "sample_count": len(values), "sample_limit": sample_size,
        "sampling_method": "stratified_non_null_rank",
        "statistic_scope": {
            "full_column": ["total_count", "non_null_count", "null_percentage", "distinct_count",
                            "uniqueness_ratio", "duplicate_count"],
            "sample": ["min_length", "max_length", "average_length", "numeric_statistics", "patterns",
                       "character_composition", "text_indicators", "date_formats", "value_indicators",
                       "local_detection", "presidio_detection", "normalization"],
        },
        "value_indicators": value_indicators(values, strings),
        "local_detection": local_detection,
        "normalization": normalization_indicators(values),
        "presidio_detection": presidio.summarize(values) if presidio is not None else None,
        "min_length": min(lengths, default=None),
        "max_length": max(lengths, default=None),
        "average_length": sum(lengths) / len(lengths) if lengths else None,
        "numeric_statistics": None if has_identifier_pattern else numeric_statistics(values),
        "patterns": [{"pattern": pattern, "count": count} for pattern, count in patterns.most_common(10)],
        "character_composition": dict(composition),
        "text_indicators": {
            "arabic_values": sum(bool(ARABIC.search(value)) and
                                 any(c.isalpha() and ARABIC.fullmatch(c) for c in value)
                                 for value in strings),
            "english_values": sum(bool(ENGLISH.search(value)) for value in strings),
        },
        "date_formats": dict(dates),
    }


def profile_database(connection, schema, sample_size=500, presidio=None):
    profiles = {}
    for entry in schema["tables"]:
        table = Table(entry["name"], MetaData(), autoload_with=connection, resolve_fks=False)
        profiles[table.name] = {
            col["name"]: profile_column(connection, table, table.c[col["name"]], sample_size, presidio)
            for col in entry["columns"]
        }
    return profiles
