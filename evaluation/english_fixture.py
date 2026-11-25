"""Fixed English-only catalog benchmark. Labels are used only by the scorer."""
import json
import sqlite3
from pathlib import Path

# field, SQLite type, semantic truth, business domain, privacy truth
SCHEMA = {
    "customer_directory": [
        ("id", "INTEGER PRIMARY KEY", "record_id", "customer", "linked"),
        ("full_name", "TEXT", "person_name", "customer", "direct"),
        ("reach", "TEXT", "email_address", "customer", "direct"),
        ("hotline", "TEXT", "phone_number", "customer", "direct"),
        ("citizen_ref", "TEXT", "saudi_national_id", "customer", "direct"),
        ("permit_no", "TEXT", "saudi_residency_id", "customer", "direct"),
        ("home_municipality", "TEXT", "city", "customer", "linked"),
        ("segment_band", "TEXT", "customer_segment", "customer", "linked"),
    ],
    "support_cases": [
        ("case_id", "INTEGER PRIMARY KEY", "record_id", "support", "none"),
        ("subject_ref", "INTEGER REFERENCES customer_directory(id)", "reference_id", "support", "linked"),
        ("asset_ref", "INTEGER REFERENCES asset_inventory(asset_id)", "reference_id", "operations", "none"),
        ("progress", "TEXT", "status", "support", "linked"),
        ("queue_bucket", "TEXT", "category", "support", "none"),
        ("elapsedMins", "INTEGER", "duration_minutes", "support", "linked"),
        ("memo", "TEXT", "free_text", "support", "uncertain"),
        ("opened_at", "TEXT", "date", "support", "linked"),
    ],
    "asset_inventory": [
        ("asset_id", "INTEGER PRIMARY KEY", "record_id", "operations", "none"),
        ("passport_code", "TEXT", "business_identifier", "operations", "none"),
        ("stock_class", "TEXT", "category", "operations", "none"),
        ("storage_area", "TEXT", "location", "operations", "none"),
        ("stock_qty", "INTEGER", "count", "operations", "none"),
        ("replacement_value", "REAL", "price", "operations", "none"),
        ("shape_payload", "TEXT", "geo_polygon", "operations", "none"),
        ("mystery_blob", "TEXT", "unknown", "operations", "uncertain"),
    ],
    "invoice_ledger": [
        ("invoice_id", "INTEGER PRIMARY KEY", "record_id", "finance", "none"),
        ("holder", "INTEGER REFERENCES customer_directory(id)", "reference_id", "finance", "linked"),
        ("settled_amt", "REAL", "payment_amount", "finance", "linked"),
        ("iso_unit", "TEXT", "currency_code", "finance", "none"),
        ("settlement_state", "TEXT", "payment_status", "finance", "linked"),
        ("payout_route", "TEXT", "saudi_iban", "finance", "direct"),
        ("posted_on", "TEXT", "date", "finance", "linked"),
        ("tax_amt", "REAL", "tax_amount", "finance", "linked"),
    ],
    "library_loans": [
        ("loan_id", "INTEGER PRIMARY KEY", "record_id", "library", "none"),
        ("borrower_ref", "INTEGER REFERENCES customer_directory(id)", "reference_id", "library", "uncertain"),
        ("branch_town", "TEXT", "city", "library", "none"),
        ("loan_state", "TEXT", "status", "library", "linked"),
        ("loan_minutes", "INTEGER", "duration_minutes", "library", "linked"),
        ("volume_title", "TEXT", "collection_title", "library", "none"),
        ("genre_bucket", "TEXT", "category", "library", "none"),
        ("remarks", "TEXT", "free_text", "library", "uncertain"),
    ],
    "training_attendance": [
        ("attendance_id", "INTEGER PRIMARY KEY", "record_id", "education", "none"),
        ("attendee_ref", "INTEGER REFERENCES customer_directory(id)", "reference_id", "education", "linked"),
        ("lesson_status", "TEXT", "status", "education", "linked"),
        ("session_length_min", "INTEGER", "duration_minutes", "education", "linked"),
        ("venue", "TEXT", "location", "education", "none"),
        ("grade_band", "TEXT", "academic_grade", "education", "linked"),
        ("course_comment", "TEXT", "free_text", "education", "uncertain"),
        ("attended_on", "TEXT", "date", "education", "linked"),
    ],
}

def choose(values, i):
    return values[i % len(values)]

def national(prefix, i):
    stem = f"{prefix}{87004211+i*71:08}"
    digits = [int(d) * (2-index%2) for index,d in enumerate(stem)]
    check = -sum(d//10+d%10 for d in digits) % 10
    return stem + str((check+1)%10 if i%13==0 else check)

def values(t, i):
    state = choose(("Pending", "Complete", "Cancelled", "In progress"), i)
    town = choose(("Riyadh", "Jeddah", "Al Khobar", "Dammam"), i)
    date = f"2025-{1+i%9:02}-{1+i%25:02}"
    note = choose(("The requester asked for a different collection time.",
                   "The operator checked the item and confirmed delivery.",
                   "A second inspection is needed before the next visit."), i)
    area = choose(("North warehouse", "Building C", "South depot", "Room 12"), i)
    if t == "customer_directory":
        return (i, choose(("Sample Resident", "Demo Borrower", "Fixture Customer"), i),
                f"person-{i}@sample.invalid" if i%13 else "invalid@", f"+9665{68001000+i:08}" if i%13 else "extension only",
                national(1,i), national(2,i+4), town, choose(("Standard", "Premium", "Community"), i))
    if t == "support_cases":
        return (i, i, i, state, choose(("General", "Hardware", "Access"), i),
                6 + i*3, note if i%7 else None, date)
    if t == "asset_inventory":
        return (i, national(2,i+8), choose(("Electrical", "Mechanical", "General"), i), area, i*3, 140+i*23.11,
                "POLYGON((0 0, 1 0, 1 1, 0 0))", choose(("..", "X19", "Pending", "2025-01-01"), i))
    if t == "invoice_ledger":
        account = f"88{7300123000+i:018}"
        check = 98-int(account+"281000")%97
        return (i, i, 40+i*18.45, choose(("SAR","USD","AED"),i),
                choose(("Paid", "Unpaid", "Overdue"),i), f"SA{check if i%13 else 0:02}{account}", date, round((40+i*18.45)*.15,2))
    if t == "library_loans":
        return (i, 9999 if i==13 else i, town, state, 60+i*15,
                choose(("Practical Meteorology", "A Brief Atlas", "History of Printing"),i),
                choose(("History", "Science", "Travel"),i), note)
    return (i, i, state, 45+i*2, area, choose(("A","B","C"),i), note, date)

def generate(root):
    root.mkdir(parents=True, exist_ok=False)
    db = root/"english_business.sqlite"
    with sqlite3.connect(db) as con:
        for t, definitions in SCHEMA.items():
            con.execute(f"CREATE TABLE {t} ("+", ".join(f"{c} {sql}" for c,sql,*_ in definitions)+")")
            con.executemany(f"INSERT INTO {t} VALUES ("+",".join("?" for _ in definitions)+")",
                            [values(t,i) for i in range(1,26)])
    labels = {t: {c: {"semantic_type": kind, "domain": domain, "personal_linkage": privacy,
                     "personal_data": {"none":"no","direct":"yes","linked":"yes","uncertain":"uncertain"}[privacy]}
                  for c,_,kind,domain,privacy in fields} for t,fields in SCHEMA.items()}
    (root/"labels.json").write_text(json.dumps(labels,indent=2)+"\n",encoding="utf-8")
    from hashlib import file_digest
    manifest={}
    for path in (db,root/"labels.json"):
        with path.open("rb") as source: manifest[path.name]=file_digest(source,"sha256").hexdigest()
    (root/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__":
    generate(Path("data/english_acceptance"))
