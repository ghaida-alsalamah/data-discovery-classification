"""Metadata normalization and conservative domain/person context."""
import re
import unicodedata
from functools import lru_cache

from .taxonomy import DOMAINS

ARABIC = str.maketrans("أإآٱى", "ااااي")
ABBREVIATIONS = {
    "dob": "birth date", "tel": "telephone", "qty": "quantity", "amt": "amount",
    "txn": "transaction", "addr": "address", "dept": "department", "emp": "employee",
    "cust": "customer", "acct": "account", "num": "number", "iq": "iqama",
    "هويه": "هوية", "اقامه": "إقامة",
}


@lru_cache(maxsize=4096)
def words(value, *, expand=True):
    value = unicodedata.normalize("NFKC", value).translate(ARABIC)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn" and c != "ـ")
    value = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = re.findall(r"[^\W_]+", value.casefold())
    if expand:
        tokens = [ABBREVIATIONS.get(token, token).translate(ARABIC) for token in tokens]
    return " ".join(tokens)


def tokens(value):
    base = set(words(value).split())
    return base | {word.removesuffix("s") for word in base if len(word) > 3}


def has(value, vocabulary):
    return bool(tokens(value) & vocabulary)


PERSON = set("patient learner pupil student guest traveller employee staff faculty customer subscriber resident member applicant مواطن مريض طالب نزيل عميل موظف متعلم مشترك مقيم مراجعي".split())
BUSINESS = set("batch vendor merchant inventory sku shipment parcel routing warehouse item product device workstation catalog asset lot supplier tracking consignment دفعة مورد منتج شحنة مخزون".split())
IDENTITY = set("identity national residency iqama passport هوية اقامة الهوية الاقامة جواز".split())
CODE = set("code ref identifier key token tag رمز معرف مرجع كود".split())
ENTITY_TYPES = {"person_name", "saudi_national_id", "saudi_residency_id", "phone_number", "email_address"}
DOMAIN_ANCHORS = {
    "saudi_iban": "finance", "currency_code": "finance", "payment_amount": "finance",
    "payment_status": "finance", "payment_method": "finance", "tax_amount": "finance",
    "salary": "workforce", "department": "workforce", "job_title": "workforce",
    "clinical_measurement": "healthcare", "clinical_code": "healthcare",
    "academic_grade": "education", "tracking_code": "logistics",
    "policy_number": "insurance", "reservation_code": "hospitality",
}


@lru_cache(maxsize=4096)
def domain_mentions(value):
    value_tokens = tokens(value)
    return {domain for domain, (_, _, aliases) in DOMAINS.items()
            if any(words(alias) and set(words(alias).split()) <= value_tokens for alias in aliases)}


def infer_domain(name, kind, table_name, table_hint, neighboring_domains, similarities, target_hint):
    scores = {}
    mentions = domain_mentions(name)
    anchor = DOMAIN_ANCHORS.get(kind)
    for domain in DOMAINS:
        field_score = .57 if domain in mentions else 0
        model_score = max(0, similarities.get(domain, 0) - .50) * .58
        neighbor_score = min(.12, .04 * neighboring_domains.count(domain))
        scores[domain] = (max(field_score, model_score)
                          + (.49 if domain == anchor else 0)
                          + (.27 if domain == table_hint else 0)
                          + (.15 if domain in domain_mentions(table_name) else 0)
                          + (.10 if domain == target_hint else 0) + neighbor_score)
    ordered = sorted(scores, key=scores.get, reverse=True)
    first, second = ordered[:2]
    if scores[first] < .27 or scores[first] - scores[second] < .10:
        return "unknown", "uncertain_or_emerging"
    source = "field_semantics_or_metadata" if first == anchor or first in mentions else "table_and_neighbors"
    return first, source
