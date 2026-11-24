"""Fresh independent synthetic fixtures. No classifier or earlier fixture imports."""
import hashlib
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# Names, semantics, privacy truth (+/-/?), and optional FK target; all defined before inference.
SECTORS = {
    "agriculture": (61879, {
        "حصاد_المزرعة": ("agriculture", """
            batchPk record_id - code_n business_identifier - ضبط_ر crop_moisture -
            dateCut date - gross_qty count - durationHrs duration_minutes -
            block_area location - lot_grade category -
        """),
        "fieldCrew": ("workforce", """
            crewPk record_id + أ_ع person_name + gate_tel phone_number + mail_work email_address +
            iqRenew saudi_residency_id + payFloor salary + work_from date + grade_hint job_title +
        """),
        "packing_runs": ("operations", """
            packPk record_id - input_ref reference_id - حصاد_المزرعة operator_ref reference_id + fieldCrew
            pack_day date + crate_total count - active_flag boolean_flag -
            retailer_email business_identifier - exception_mix unknown ?
        """),
    }),
    "construction": (103751, {
        "أصول_الموقع": ("construction", """
            equipmentPk record_id - serialContact business_identifier - machine_zone location -
            warranty_end date - elevation elevation_measurement - fleet_state status -
            rentable boolean_flag - rental_fee price -
        """),
        "sitePermit": ("construction", """
            permitPk record_id - machine_ref reference_id - أصول_الموقع
            permit_code business_identifier - permitDay date - ف_ص category -
            processing_mins duration_minutes - notes_text free_text ? rate_iso currency_code -
        """),
        "permitApplicants": ("customer", """
            entryPk record_id + accountName person_name + private_phone phone_number +
            ه_و saudi_national_id + contactbox email_address + permit_ref reference_id + sitePermit
            municipality city + enrolledOn date +
        """),
    }),
    "museum": (219443, {
        "artifactLoan": ("cultural_services", """
            loanSeq record_id - item_guide business_identifier - shelf_zone location -
            display_title collection_title - issue_day date - suggested_fee price -
            certificate_state status - memo_other unknown ?
        """),
        "memberBook": ("customer", """
            memberSeq record_id + اسم_ش person_name + dueDial phone_number + mailbox_notice email_address +
            tag_w business_identifier - member_since date + homeTown city + family_plan category +
        """),
        "deskJournal": ("finance", """
            ledgerSeq record_id - member_ref reference_id + memberBook object_ref reference_id - artifactLoan
            amount_due transaction_amount + paid_at date + pay_state payment_status +
            locale_money currency_code - billing_region saudi_iban +
        """),
    }),
}
STATUS = {"+": "yes", "-": "no", "?": "uncertain"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, content):
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def parse(text):
    tokens = iter(text.split())
    row = []
    for name in tokens:
        kind, personal = next(tokens), next(tokens)
        target = next(tokens) if kind == "reference_id" else None
        row.append((name, kind, personal, target))
    return row


def invalid_identity(prefix, seq):
    stem = f"{prefix}{seq:08d}"
    checksum = sum(sum(divmod(int(digit) * (2 if index % 2 == 0 else 1), 10))
                   for index, digit in enumerate(stem))
    return stem + str((2 - checksum) % 10)


def make_value(kind, i, rng):
    if i % 23 == 0:
        return None
    seq = rng.randrange(10**7, 10**8)
    if kind in {"saudi_national_id", "saudi_residency_id", "business_identifier"}:
        if i % 19 == 0:
            return f"unverified-{seq:x}"
        return invalid_identity(1 if kind == "saudi_national_id" else 2, seq)
    if kind == "phone_number":
        return "missing extension" if i % 8 == 0 else f"+96600{seq % 10**7:07d}"
    if kind == "email_address":
        return "bad@" if i % 13 == 0 else f"sample-{seq:x}@offline.invalid"
    if kind == "saudi_iban":
        return f"SA00{seq:020d}"
    if kind == "date":
        day = date(2021, 6, 9) + timedelta(days=rng.randrange(1820))
        return "2034-02-31" if i % 19 == 0 else day.strftime("%d/%m/%Y") if i % 2 else day.isoformat()
    if kind in {"salary", "price", "transaction_amount", "crop_moisture", "elevation_measurement"}:
        return round(rng.paretovariate(3.2) * (1300 if kind == "salary" else 13), 2)
    if kind == "boolean_flag":
        return int(rng.random() > .4)
    if kind in {"count", "duration_minutes"}:
        return -2 if i % 37 == 0 else int(rng.triangular(0, 95, 30))
    options = {
        "person_name": ["Rashid Testcase", "Noura Fiction", "نادر افتراضي", "ريم تجريبي"],
        "city": ["بريدة", "Buraydah", "طريف", "Turaif", "TURAIF"],
        "location": ["Block B", "قطاع ب", "Zone C", "الفناء"],
        "category": ["tier bx", "Track III", "الفئة ج"],
        "job_title": ["Garden lead", "منسق افتراضي", "Relief technician"],
        "status": ["قيد المراجعة", "Scheduled", "Deferred"],
        "payment_status": ["Collected", "Deferred", "معاد"],
        "currency_code": ["SAR", "AED", "EUR", "SAR"],
        "collection_title": ["Fixture engraving", "نقش تجريبي", "Synthetic case study"],
        "free_text": ["Synthetic note only.", "بيان اختباري مستقل.", "See archived fixture."],
        "unknown": ["?", "17-67", "a@fiction.invalid", "مزيج", "maybe", "2022-06-04"],
    }
    return rng.choice(options[kind])


def build(path, seed, spec):
    rng = random.Random(seed)
    schema = {table: (domain, parse(text)) for table, (domain, text) in spec.items()}
    ids = {table: sorted(rng.sample(range(800, 17000), 86 + index * 47))
           for index, table in enumerate(schema)}
    truth = {}
    with sqlite3.connect(path) as db:
        for table, (domain, columns) in schema.items():
            truth[table] = {}
            defs = []
            for name, kind, pii, target in columns:
                truth[table][name] = {"semantic_type": kind, "personal_data": STATUS[pii],
                                      "domain": "finance" if kind in {"currency_code", "saudi_iban"} else domain}
                typ = ("INTEGER" if kind in {"record_id", "reference_id", "boolean_flag", "count", "duration_minutes"}
                       else "REAL" if kind in {"price", "salary", "transaction_amount", "crop_moisture", "elevation_measurement"}
                       else "TEXT")
                typ = typ + " PRIMARY KEY" if kind == "record_id" else typ
                if target:
                    typ += f" REFERENCES {quote(target)}({quote(schema[target][1][0][0])})"
                defs.append(quote(name) + " " + typ)
            db.execute(f"CREATE TABLE {quote(table)}(" + ",".join(defs) + ")")
            for i, key in enumerate(ids[table], 1):
                row = [key if k == "record_id" else
                       (999999 if k == "reference_id" and i % 43 == 0 else rng.choice(ids[target]))
                       if target else make_value(k, i, rng) for _, k, _, target in columns]
                db.execute(f"INSERT INTO {quote(table)} VALUES (" + ",".join("?" for _ in row) + ")", row)
    return truth


if __name__ == "__main__":
    root = Path("data/local_llm/fresh")
    seal = root.parent / "experiment_seal.json"
    if not seal.is_file():
        raise ValueError("Seal the experiment before building the new holdout.")
    root.mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "databases").mkdir()
    for name, (seed, specification) in SECTORS.items():
        truth = build(root / "databases" / (name + ".sqlite"), seed, specification)
        assert sum(map(len, truth.values())) == 24
        save(root / "labels" / (name + ".json"), truth)
    save(root / "manifest.json", {"seal": sha(seal), "seeds": {name: spec[0] for name, spec in SECTORS.items()},
         "files": {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.glob("*/*"))}})
