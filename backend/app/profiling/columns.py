import math
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from numbers import Real

import pandas as pd
from sqlalchemy import MetaData, Table, distinct, func, select, type_coerce
from sqlalchemy.types import NullType

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


def profile_column(connection, table, column, sample_size=500):
    if type(sample_size) is not int or sample_size < 1:
        raise ValueError("sample_size must be a positive integer")
    total, non_null, distinct_count = connection.execute(
        select(func.count(), func.count(column), func.count(distinct(column))).select_from(table)
    ).one()
    # type_coerce bypasses reflected result processors for mixed SQLite storage types.
    sample = select(type_coerce(column, NullType())).where(column.is_not(None))
    order = list(table.primary_key.columns) or [column]
    values = list(connection.scalars(sample.order_by(*order).limit(sample_size)))

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
        "min_length": min(lengths, default=None),
        "max_length": max(lengths, default=None),
        "average_length": sum(lengths) / len(lengths) if lengths else None,
        "numeric_statistics": numeric_statistics(values),
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


def profile_database(connection, schema, sample_size=500):
    profiles = {}
    for entry in schema["tables"]:
        table = Table(entry["name"], MetaData(), autoload_with=connection, resolve_fks=False)
        profiles[table.name] = {
            col["name"]: profile_column(connection, table, table.c[col["name"]], sample_size)
            for col in entry["columns"]
        }
    return profiles
