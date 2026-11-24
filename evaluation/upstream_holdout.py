"""New synthetic municipal, library, and facility schemas. No classifier imports."""
import hashlib
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# Column:semantic type:personal truth:optional FK target. D denotes direct identifier.
SPEC = {
    "municipal": (46137, {
        "بل_طلبات": ("municipal_services", [
            "application_seq:record_id:N", "account_ref:reference_id:L:resident_directory",
            "received_at:date:L", "geo_section:location:L", "parcel_code:business_identifier:N",
            "stage:status:L", "processing_duration:duration_minutes:L", "service_count:count:N",
            "rent_charge:price:N", "district_fee_class:category:N", "ملاحظة_ق:free_text:U",
            "z_address_map:geo_polygon:N",
        ]),
        "resident_directory": ("customer", [
            "resident_seq:record_id:L", "الاسم_ط:person_name:D", "postal_tag:saudi_residency_id:D",
            "main_line:phone_number:D", "via_mail:email_address:D", "موطن:city:L",
            "joined_at:date:L", "declaration_flag:boolean_flag:L", "visitor_pass:business_identifier:N",
            "primary_place:location:L", "member_segment:category:L", "alt_payload:unknown:U",
        ]),
    }),
    "library": (99581, {
        "مقتنيات_المكتبة": ("cultural_services", [
            "catalog_seq:record_id:N", "call_mark:business_identifier:N", "عنوان_ن:collection_title:N",
            "public_summary:free_text:N", "edition_state:status:N", "genre_group:category:N",
            "branch_town:city:N", "release_day:date:N", "loan_period:duration_minutes:N",
            "replacement_rate:price:N", "item_count:count:N", "in_stock:boolean_flag:N",
        ]),
        "borrower_ledger": ("finance", [
            "ledger_seq:record_id:N", "item_ref:reference_id:N:مقتنيات_المكتبة",
            "borrower_full_name:person_name:D", "ه_ا:saudi_national_id:D", "other_mail:email_address:D",
            "emergency_tel:phone_number:D", "paid_day:date:L", "fees:payment_amount:L",
            "receipt_state:payment_status:L", "iso_hint:currency_code:N", "office_room:location:N",
            "deposit_partition:saudi_iban:D",
        ]),
    }),
    "facilities": (77293, {
        "maintenance_registry": ("operations", [
            "job_seq:record_id:N", "asset_ref:reference_id:N:room_catalog",
            "work_order:business_identifier:N", "field_tech:person_name:D",
            "dispatch_on:date:L", "after_hours:boolean_flag:L", "service_minutes:duration_minutes:L",
            "ح_ج:phone_number:D", "notice_address:email_address:D", "status_flag:status:L",
            "meters_per_unit:engineering_measure:N", "other_record:unknown:U",
        ]),
        "room_catalog": ("catalog", [
            "tag_seq:record_id:N", "رقم_ه:business_identifier:N", "unit_label:service_name:N",
            "station_area:location:N", "nearest_town:city:N", "division:category:N",
            "lease_price:price:N", "price_code:currency_code:N", "access_count:count:N",
            "survey_date:date:N", "usage_state:status:N", "facility_ready:boolean_flag:N",
        ]),
    }),
}
STATUS = {"D": "yes", "L": "yes", "N": "no", "U": "uncertain"}
LINKAGE = {"D": "direct", "L": "linked", "N": "none", "U": "uncertain"}


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def draw(kind, row, rng, offset):
    seq = (offset * 12691 + row * 277) % 10**8
    if row % 29 == 0:
        return None
    if kind in {"saudi_national_id", "saudi_residency_id", "business_identifier"}:
        prefix = 1 if kind == "saudi_national_id" else 2
        base = f"{prefix}{seq:08d}"
        weighted = sum(sum(divmod(int(x) * (2 if i % 2 == 0 else 1), 10)) for i, x in enumerate(base))
        return base + str((8 - weighted) % 10) if row % 11 else f"unverified-{seq:x}"
    if kind == "phone_number":
        return f"+96600{seq % 10**7:07d}" if row % 11 else "test extension"
    if kind == "email_address":
        return f"test-{seq:x}@discovery.invalid" if row % 13 else "bad@"
    if kind == "saudi_iban":
        return f"SA00{seq:020d}"
    if kind == "boolean_flag":
        return rng.randint(0, 1)
    if kind in {"count", "duration_minutes"}:
        return rng.randrange(120) if row % 38 else -2
    if kind in {"engineering_measure", "payment_amount", "price"}:
        return round(rng.triangular(8, 11000, 172), 2)
    if kind == "date":
        d = date(2022, 3, 2) + timedelta(days=rng.randrange(870))
        return d.isoformat() if row % 4 else d.strftime("%d/%m/%Y")
    return rng.choice({
        "phone": ("placeholder",), "city": ("طبرجل", "Tabarjal", "عرعر", "Arar", "Umluj", "أملج"),
        "location": ("Block D", "قطاع د", "Zone C", "الفناء"),
        "service_name": ("Fixture study room", "وحدة افتراضية", "Demo workspace"),
        "person_name": ("Samira Fiction", "Khaled Example", "هالة تجريبي", "مروان اختبار"),
        "category": ("red tier", "مسار ج", "Level A", "LEVEL A"),
        "status": ("Open", "مجدول", "Completed"), "payment_status": ("Settled", "معلق", "Failed"),
        "free_text": ("Synthetic observation only.", "بيان للاختبار فقط.", "Inspect at next scheduled visit."),
        "unknown": ("--", "N/A", "123Z", "مزيج", "example@invalid.test", "17/05/2025"),
        "collection_title": ("Exhibit training sample", "مخطوطة صناعية", "Fictional study volume"),
        "currency_code": ("SAR", "AED", "SAR", "EUR"), "geo_polygon": ("POINT(10 20)", "POINT(1 1)"),
    }[kind])


def build(path, seed, tables):
    rng = random.Random(seed)
    counts = {table: 79 + index * 41 for index, table in enumerate(tables)}
    truth = {}
    with sqlite3.connect(path) as db:
        for index, (table, (domain, declarations)) in enumerate(tables.items()):
            truth[table] = {}
            parsed = [item.split(":") for item in declarations]
            columns = []
            for name, kind, person, *link in parsed:
                truth[table][name] = {"semantic_type": kind, "domain": domain,
                                     "personal_data": STATUS[person], "personal_linkage": LINKAGE[person]}
                typ = ("INTEGER" if kind in {"record_id", "reference_id", "count", "duration_minutes", "boolean_flag"}
                       else "REAL" if kind in {"engineering_measure", "payment_amount", "price"} else "TEXT")
                definition = f"{quote(name)} {typ}"
                if kind == "record_id":
                    definition += " PRIMARY KEY"
                if link:
                    target = link[0]
                    parent = tables[target][1][0].split(":")[0]
                    definition += f" REFERENCES {quote(target)}({quote(parent)})"
                columns.append(definition)
            db.execute(f"CREATE TABLE {quote(table)}(" + ",".join(columns) + ")")
            for row in range(1, counts[table] + 1):
                values = [row if kind == "record_id" else
                          (999999 if row % 37 == 0 else rng.randint(1, counts[link[0]]))
                          if link else draw(kind, row, rng, seed + index * 13 + col)
                          for col, (_, kind, _, *link) in enumerate(parsed)]
                db.execute(f"INSERT INTO {quote(table)} VALUES (" + ",".join("?" for _ in values) + ")", values)
    return truth


def generate(root, seal):
    if not seal.is_file():
        raise ValueError("Seal classifier code and mappings first.")
    root.mkdir(parents=True, exist_ok=False)
    (root / "databases").mkdir()
    (root / "labels").mkdir()
    for name, (seed, tables) in SPEC.items():
        truth = build(root / "databases" / f"{name}.sqlite", seed, tables)
        assert sum(map(len, truth.values())) == 24
        save(root / "labels" / f"{name}.json", truth)
    save(root / "manifest.json",
         {"seal_sha256": sha(seal), "files": {p.relative_to(root).as_posix(): sha(p) for p in root.glob("*/*")}})


if __name__ == "__main__":
    generate(Path("data/upstream/fresh"), Path("data/upstream/seal.json"))
