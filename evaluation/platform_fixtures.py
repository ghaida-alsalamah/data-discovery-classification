"""Independent, synthetic test databases for native classification workflows."""
import argparse
from datetime import date, timedelta
from hashlib import file_digest
import json
from pathlib import Path
from random import Random
import sqlite3

ROOT = Path("data/platform_adoption")
ROWS = 64

# Table groups and field purposes are annotated independently of the evaluated platforms.
# D is a direct identifier, L is a person-linked attribute or reference, N is neither.
# Optional foreign key targets refer to the first column of an earlier table.
SCHEMAS = {
    "community_care": (38519, {
        "intake_book": ("patient_intake", """
            visitant_key:record_id:L personal_name:person_name:D wire_slot:email_address:D
            telephone:phone_number:D day_zero:date:L eligibility_band:category:L
            enrollment_state:status:L confirmation:business_identifier:N"""),
        "service_options": ("service_catalog", """
            option_key:record_id:N display_text:service_name:N option_code:service_code:N
            standard_charge:price:N currency:currency_code:N enabled:boolean_flag:N"""),
        "treatment_clock": ("care_activity", """
            encounter_key:record_id:N participant:reference_id:L:intake_book
            selection:reference_id:N:service_options time_opened:date:L
            elapsed:duration_minutes:L priority_band:category:L recheck_flag:boolean_flag:L
            notes:free_text:L"""),
        "diagnostics_ledger": ("care_activity", """
            order_key:record_id:N case_link:reference_id:L:treatment_clock
            request_day:date:L analysis_code:clinical_code:L recorded_measure:clinical_measurement:L
            supply_batch:business_identifier:N followup_state:status:L"""),
        "clinic_sites": ("facilities", """
            site_key:record_id:N site_label:service_name:N municipality:city:N
            switchboard:phone_number:N capacity_count:count:N occupancy:percentage:N"""),
    }),
    "freight_brokerage": (89177, {
        "operator_book": ("carrier_contacts", """
            operator_key:record_id:L given_name:person_name:D family_name:person_name:D
            return_route:email_address:D private_line:phone_number:D
            authorization_day:date:L residency_number:saudi_residency_id:D"""),
        "rate_board": ("pricing", """
            rate_key:record_id:N tariff_code:service_code:N base_price:price:N currency_iso:currency_code:N
            inactive_flag:boolean_flag:N rate_region:service_region:N"""),
        "movement_queue": ("dispatch", """
            movement_key:record_id:N handler:reference_id:L:operator_book assigned_rate:reference_id:N:rate_board
            tracking_ref:tracking_code:N departure_date:date:L delivery_state:status:L
            package_count:count:L gross_mass:mass:L"""),
        "surcharge_entries": ("billing", """
            charge_key:record_id:N movement_ref:reference_id:L:movement_queue
            invoice_day:date:L charge_amount:transaction_amount:L tax_amount:tax_amount:L
            settlement:payment_status:L tender:payment_method:L"""),
        "cargo_units": ("inventory", """
            asset_key:record_id:N contact_email:business_identifier:N inventory_serial:business_identifier:N
            hold_zone:location:N items_count:count:N maintenance_due:date:N tare_mass:mass:N"""),
    }),
    "arts_grants": (61583, {
        "application_contacts": ("applicant_contacts", """
            contact_key:record_id:L name_on_form:person_name:D email_address:email_address:D
            signal_2:phone_number:D birth_yr:year:L home_town:city:L status:status:L"""),
        "award_calls": ("program_directory", """
            call_key:record_id:N call_title:service_name:N track_type:category:N
            open_date:date:N submission_deadline:date:N eligible_flag:boolean_flag:N
            ceiling_amount:financial_amount:N"""),
        "funding_packets": ("funding_activity", """
            packet_key:record_id:N packet_subject:reference_id:L:application_contacts
            funding_call:reference_id:N:award_calls submitted_on:date:L
            request_amount:financial_amount:L project_description:free_text:L
            registry_tag:business_identifier:N outcome:status:L"""),
        "panel_observations": ("funding_activity", """
            observation_key:record_id:N packet_link:reference_id:L:funding_packets
            reviewed_on:date:L assessment_band:category:L award_probability:percentage:L
            duration_minutes:duration_minutes:L reviewer_comment:free_text:L"""),
        "disbursements": ("payments", """
            payment_key:record_id:N approved_item:reference_id:L:funding_packets
            paid_on:date:L payment_amount:payment_amount:L payment_currency:currency_code:N
            payment_state:payment_status:L external_code:business_identifier:N"""),
    }),
}
NAMES = ("Lena Halberg", "Marco Delmar", "Maya Northall", "Naomi Alderwick",
         "David Bellward", "Nur Calder", "Nora Vassel", "Yusuf Rennell",
         "Irene Westler", "Alice Boberry", "Owen Willerton", "Sara Moseley")
CITIES = ("Durham", "Burlington", "Halifax", "Chester", "Lancaster", "Portland")
STATES = ("Awaiting approval", "Completed", "Open", "Rejected", "Queued")
SERVICES = ("Weekend access", "Equipment rental", "Coordination session", "Temporary storage")
FREE_TEXT = (
    "The record was reviewed after a routine check. An additional document has been requested.",
    "The team accepted the new submission and attached it to the existing file for review.",
    "A scheduled follow-up is pending. Confirm the recorded details at the next meeting.",
    "The activity can proceed after the second reviewer confirms the supporting documentation.",
)
NUMERIC = {
    "record_id": "INTEGER", "reference_id": "INTEGER", "duration_minutes": "INTEGER",
    "count": "INTEGER", "year": "INTEGER", "percentage": "DECIMAL(12,3)",
    "mass": "DECIMAL(12,3)", "clinical_measurement": "DECIMAL(12,3)",
    "financial_amount": "DECIMAL(12,2)", "price": "DECIMAL(12,2)",
    "payment_amount": "DECIMAL(12,2)", "tax_amount": "DECIMAL(12,2)",
    "transaction_amount": "DECIMAL(12,2)", "boolean_flag": "BOOLEAN",
}
MONEY = {"financial_amount", "price", "payment_amount", "tax_amount", "transaction_amount"}
PERSONAL = {"D": "yes", "L": "yes", "N": "no"}
LINKAGE = {"D": "direct", "L": "linked", "N": "none"}


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def residency_id(row, rng):
    base = "2" + str(rng.randrange(10**8)).zfill(8)
    weighted = [int(digit) * (2 - i % 2) for i, digit in enumerate(base)]
    check = -sum(sum(divmod(n, 10)) for n in weighted) % 10
    return base + str((check + (row % 13 == 0)) % 10)


def value(field, kind, row, rng):
    if kind == "person_name":
        name = NAMES[rng.randrange(len(NAMES))]
        if field == "given_name":
            return name.split()[0]
        if field == "family_name":
            return name.split()[1]
        return name
    if kind == "email_address":
        return f"{NAMES[row % len(NAMES)].lower().replace(' ','.')}.{row}@example.com"
    if kind == "phone_number":
        if row % 17 == 0:
            return "extension pending"
        return f"+1 (202) 555-{100 + row:04d}" if row % 2 else f"202-555-{100+row:04d}"
    if kind == "saudi_residency_id":
        return residency_id(row, rng)
    if kind == "record_id":
        return 1000 + row
    if kind == "reference_id":
        return 1000 + rng.randint(1, ROWS)
    if kind == "date":
        return (date(2022, 7, 1) + timedelta(days=rng.randrange(1400))).isoformat()
    if kind == "year":
        return rng.randint(1950, 2005)
    if kind in MONEY:
        return round(rng.triangular(2, 6800, 150), 2)
    if kind in {"count", "duration_minutes"}:
        return rng.randrange(3, 270)
    if kind == "boolean_flag":
        return row % 3 == 0
    if kind == "percentage":
        return round(rng.uniform(5, 99), 1)
    if kind == "clinical_measurement":
        return round(rng.gauss(70, 6), 1)
    if kind == "mass":
        return round(rng.uniform(5, 950), 2)
    if kind in {"business_identifier", "service_code", "clinical_code", "tracking_code"}:
        if field == "contact_email":
            return f"202555{100+row:04d}"
        if field == "inventory_serial":
            return str(rng.randrange(1000000000, 3000000000))
        return f"{kind[:3].upper()}-{rng.randint(20000, 99999)}"
    return rng.choice({
        "status": STATES, "payment_status": ("Paid", "Pending", "Failed", "Refunded"),
        "category": ("Standard", "Priority", "Basic", "Special handling"),
        "service_name": SERVICES, "city": CITIES, "location": ("Bay 3", "Rack 16", "Zone D"),
        "service_region": ("Northern", "Coastal", "Central", "Southern"),
        "payment_method": ("Invoice", "Card", "Bank transfer"),
        "currency_code": ("SAR", "USD", "GBP"), "free_text": FREE_TEXT,
    }[kind])


def fixture(root, name, seed, tables):
    rng = Random(seed)
    truth = {}
    sql = ["BEGIN;"]
    db = root / (name + ".sqlite")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for table, (domain, specification) in tables.items():
            fields = [spec.split(":") for spec in specification.split()]
            column_defs = []
            truth[table] = {}
            for field, kind, privacy, *target in fields:
                dtype = NUMERIC.get(kind, "DATE" if kind == "date" else "TEXT")
                key = " PRIMARY KEY" if kind == "record_id" else ""
                if target:
                    first_field = tables[target[0]][1].split()[0].split(":")[0]
                    key = f" REFERENCES {target[0]}({first_field})"
                column_defs.append(f"{field} {dtype}{key}")
                truth[table][field] = {"semantic_type": kind, "domain": domain,
                                       "personal_data": PERSONAL[privacy], "personal_linkage": LINKAGE[privacy]}
            ddl = f"CREATE TABLE {table} (" + ", ".join(column_defs) + ");"
            conn.execute(ddl)
            sql.append(ddl)
            for row in range(1, ROWS + 1):
                vals = [value(field, kind, row, rng) for field, kind, *_ in fields]
                if row % 29 == 0:
                    vals[-1] = None
                conn.execute(f"INSERT INTO {table} VALUES (" + ", ".join("?" for _ in vals) + ")", vals)
                rendered = [("NULL" if v is None else "TRUE" if v is True else "FALSE" if v is False
                             else "'" + v.replace("'", "''") + "'" if isinstance(v, str) else str(v)) for v in vals]
                sql.append(f"INSERT INTO {table} VALUES (" + ", ".join(rendered) + ");")
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    source = root / (name + ".sql")
    source.write_text("\n".join([*sql, "COMMIT;", ""]), encoding="utf-8")
    labels = root / (name + "_labels.json")
    save(labels, truth)
    return {p.name: digest(p) for p in (db, source, labels)}


def freeze(root):
    root.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, (seed, tables) in SCHEMAS.items():
        hashes.update(fixture(root, name, seed, tables))
    save(root / "fixtures.json", {"seed_by_database": {n: s for n, (s, _) in SCHEMAS.items()},
                                  "rows_per_table": ROWS, "inputs": hashes})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    freeze(parser.parse_args().output)
