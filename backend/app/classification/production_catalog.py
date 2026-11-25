"""Default local catalog. Verify observable types first, then route bounded ambiguities."""
import re
from collections import defaultdict

import httpx
import phonenumbers
from presidio_analyzer.predefined_recognizers import UsSsnRecognizer

from .context import BUSINESS, PERSON, has
from .evidence_catalog import assign
from .english import normalize
from .engine import DIRECT
from .local_llm import hints
from .open_catalog import accept, infer, make_payload
from .relational_catalog import apply_privacy, refine

DIRECT_EXTENSIONS = {"ssn": "government_id"}
KEYS = {"record_id", "reference_id"}
EXTENDED = {"ssn": "identifier", "postal_code": "location", "age": "count",
            "year": "date", "percentage": "measurement", "web_address": "identifier"}
REGIONS = ("SA", "US", "GB", "CA", "AU")
SSN = UsSsnRecognizer()
ROLE_NAMES = {"first", "last", "given", "family", "middle", "surname", "full"}


def signature(value, pattern):
    return isinstance(value, (str, int)) and re.fullmatch(pattern, str(value).strip(), re.ASCII) is not None


def phone_valid(value):
    if not signature(value, r"[+0-9][0-9 ().-]{6,24}"):
        return False
    raw = str(value).strip()
    # Bare digit strings need a recognized international prefix or a country format.
    for region in (("US",) if raw.startswith("+") else REGIONS):
        try:
            number = phonenumbers.parse(raw, region)
            if phonenumbers.is_valid_number(number):
                return True
        except phonenumbers.NumberParseException:
            continue
    return False


def set_type(row, kind, detail):
    if kind not in EXTENDED:
        assign(row, kind, "independent_content_check", detail, True)
    else:
        row.update(semantic_type=kind, semantic_category=EXTENDED[kind], subtype_status="identified",
                   semantic_verified=True, explanation=detail, confidence=.76)
        row["supporting_evidence"] = [{"source":"independent_content_check", "family":"value_pattern",
                                       "detail":detail,"weight":0}]
    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "semantic"]


def direct(row, kind, detail):
    set_type(row, kind, detail)
    row.update(personal_data="yes", personal_linkage="direct", privacy_role="direct_identifier",
               sensitivity="restricted" if kind=="ssn" else "confidential",
               personal_linkage_evidence={"method":"independent_content_check","relationship_ids":[]})
    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]


def proportion(values, predicate):
    return sum(predicate(v) for v in values) / max(1, len(values))


def name_shape(values):
    return proportion(values, lambda v: isinstance(v,str) and 1 <= len(v.strip()) <= 45
                      and any(c.isalpha() for c in v)
                      and all(c.isalpha() or c in " .'-" for c in v))


def corroborate(row, values, profile, table_subject, paired_name):
    if len(values) < 3:
        return
    name = normalize(row["column_name"])
    words = set(name.split())
    if words & {"ssn"} or {"social","security"} <= words:
        if proportion(values, lambda v: signature(v, r"(?:\d{3}-\d{2}-\d{4}|\d{9})")
                      and not SSN.invalidate_result(str(v))
                      and int(re.sub(r"\D", "", str(v))[:3]) < 900) >= .75:
            direct(row, "ssn", "SSN metadata and local valid-format checks agree.")
            return
    if row["semantic_type"] in KEYS:
        return
    personal_scope = table_subject or paired_name
    if words & {"phone", "mobile", "telephone", "cell"} and not has(name, BUSINESS):
        if proportion(values, phone_valid) >= .75:
            if personal_scope or words & {"personal","home","mobile","cell"}:
                direct(row, "phone_number", "Phone metadata and validated numbering plans support an individual contact.")
            elif row["semantic_type"] not in DIRECT:
                set_type(row, "phone_number", "Phone metadata and validated numbering plans support this contact field.")
                row["review_dimensions"] = sorted(set(row["review_dimensions"]) | {"privacy"})
            return
    name_scope = paired_name or table_subject and (words & ROLE_NAMES or words == {"name"})
    if "name" in words and not has(name, BUSINESS) and name_scope:
        if name_shape(values) >= .85:
            direct(row, "person_name", "Name structure and person scope corroborate this identifying field.")
            return
    if row["semantic_type"] in DIRECT and row["semantic_verified"]:
        return

    rules = [
        ("postal_code", bool(words & {"postal","zip","postcode"}),
         lambda v: signature(v, r"[A-Za-z0-9][A-Za-z0-9 -]{2,9}") and any(c.isdigit() for c in str(v))),
        ("year", "year" in words,
         lambda v: signature(v, r"\d{4}") and 1000 <= int(v) <= 2300),
        ("age", words == {"age"},
         lambda v: signature(v, r"\d{1,3}") and 0 <= int(v) <= 130),
        ("percentage", bool(words & {"percentage","percent","pct"}),
         lambda v: isinstance(v,(int,float)) and 0 <= v <= 100 or signature(v,r"[0-9]{1,2}(?:\.\d+)?%")),
        ("web_address", bool(words & {"url","website","homepage"}),
         lambda v: signature(v,r"https?://[^\s/]+\.[^\s]+")),
        ("boolean_flag", bool(words & {"active","enabled","flag","valid"}) or name.startswith(("is ","has ")),
         lambda v: str(v).strip().lower() in {"0","1","true","false","yes","no"}),
    ]
    for kind, named, validates in rules:
        if named and proportion(values, validates) >= .85:
            set_type(row, kind, "The field purpose and sampled values agree with this portable format.")
            return
    parts = profile["local_detection"].get("date", {})
    if words & {"date","datetime","timestamp"} and parts.get("format_valid",0) >= .75 * profile["sample_count"]:
        set_type(row, "date", "Temporal metadata and successful date parsing corroborate the type.")


def route_context(rows, tables, profiles, info, runtime):
    selected = []
    for row in rows:
        if row["semantic_verified"] or row["semantic_type"] in KEYS:
            row["context_status"] = "verified_locally"
            continue
        row["context_status"] = "not_routed"
        t,c = row["table_name"],row["column_name"]
        p = profiles[t][c]
        if p["sample_count"] >= 3 and normalize(c):
            priority = (row["personal_data"] == "uncertain",
                        row["semantic_type"] in {"unknown","identifier"},
                        p["sample_count"])
            selected.append((priority,t,c,row))
    if runtime is None or not selected:
        return
    # One model call per database, independent of schema width. Whole-catalog evidence is reusable.
    chosen = sorted(selected,key=lambda x:(x[0], x[1], x[2]),reverse=True)[:6]
    all_fields = {}
    for i, (_, t,c,row) in enumerate(chosen):
        token=f"f{i}"
        table=tables[t]
        field=next(col for col in table["columns"] if col["name"]==c)
        payload=make_payload(table,{c:row},profiles[t],info.get(t,{}),{token:field})
        value = payload["fields"][token]
        for key in ("name", "description"):
            value[key] = hints(value[key])
        value["references"] = [hints(ref) for ref in value["references"]]
        all_fields[token] = {**value, "table": hints(payload["table"]),
                             "neighbors": [hint for name in payload["neighbors"] if (hint := hints(name))][:8]}
    try:
        answer=infer(runtime,{"table":"multiple independent table contexts","fields":all_fields})
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        for _,_,_,row in chosen:
            row["context_status"]="fallback"
        return
    for i, (_,t,c,row) in enumerate(chosen):
        column=next(col for col in tables[t]["columns"] if col["name"]==c)
        # A multi-table prompt cannot establish a person entity for any particular table.
        accept(row,column,profiles[t][c],answer["columns"][f"f{i}"],"uncertain")
        if row["context_privacy_hypothesis"] in {"direct","linked"} and row["personal_data"] == "no":
            row.update(personal_data="uncertain",personal_linkage="uncertain",sensitivity="undetermined",
                       privacy_role="unresolved_context")
            row["review_dimensions"]=sorted(set(row["review_dimensions"])|{"privacy"})


def finalize(connection, rows, schema, profiles, samples, relationships, checks, metadata, runtime):
    tables={t["name"]:t for t in schema["tables"]}
    by_table=defaultdict(dict)
    for row in rows:
        by_table[row["table_name"]][row["column_name"]]=row
    subjects={t for t, fields in by_table.items()
              if has(t, PERSON) and not has(t,BUSINESS)
              or any(r["semantic_type"]=="email_address" and r["semantic_verified"] for r in fields.values())}
    roots=set()
    for t, fields in by_table.items():
        paired=sum("name" in normalize(c).split() and bool(set(normalize(c).split())&ROLE_NAMES)
                   and name_shape(samples[t][c])>=.85 and len(samples[t][c])>=3 for c in fields)>=2
        for c,row in fields.items():
            corroborate(row,samples[t][c],profiles[t][c],t in subjects,paired)
        identities={r["semantic_type"] for r in fields.values() if r["personal_linkage"]=="direct"}
        if (tables[t]["primary_key"]["constrained_columns"] and "person_name" in identities
                and (paired or len(identities)>1 or t in subjects)):
            roots.add(t)
    rows = refine(connection, rows, schema, profiles, samples, relationships, checks, metadata, resolve_privacy=False)
    for t, fields in by_table.items():
        observed = sum(r["semantic_verified"] and r["semantic_type"] not in KEYS for r in fields.values())
        if observed>=2 and tables[t]["primary_key"]["constrained_columns"]:
            for row in fields.values():
                if row["domain_resolution"]=="discovered_table_subject":
                    row["domain_resolution"]="corroborated_table_group"
                    row["review_dimensions"]=[d for d in row["review_dimensions"] if d!="domain"]

    route_context(rows,tables,profiles,metadata.get("tables",{}),runtime)
    apply_privacy(connection,rows,tables,by_table,relationships,checks,extra_roots=roots)
    for row in rows:
        kind=row["semantic_type"]
        row["semantic_path"]=list(dict.fromkeys(x for x in (row["semantic_category"],kind) if x!="unknown"))
        row["classification_resolution"]=row["subtype_status"] if kind!="unknown" else "unresolved"
        row["review_required"]=bool(row["review_dimensions"])
    return rows
