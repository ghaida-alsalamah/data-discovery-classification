"""Final holdout authored after the engine seal. No application or fixture imports."""
import hashlib
import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Table and field contracts are authored here before classifier execution.
# kind/+ indicates personal, kind/- non-personal, kind/? uncertain.
DATA = {
 "logistics": [
  ("pickWave", "operations", 109, """
   waveSeq record_id/- biz_mark business_identifier/- depot_locator location/- act_day date/-
   items_picked count/- elapsed_min duration_minutes/- pack_state status/- handoff_flag boolean_flag/-
   cargo_family category/- وصف_ح free_text/- area_shape geo_polygon/- bin_token business_identifier/-
   bay_class category/-
  """),
  ("أوامر_الشحن", "logistics", 389, """
   manifestSeq record_id/- waveRef reference_id/-@pickWave consigneeRef reference_id/+@recipientBook
   تع_ش tracking_code/- despatchAt date/+ arrival_hub location/+ package_total count/+
   insured_amount financial_amount/+ cod_currency currency_code/- delayMins duration_minutes/+
   transport_mode category/- proof_fragment unknown/? pallet_cell business_identifier/-
  """),
  ("recipientBook", "customer", 197, """
   recipientSeq record_id/+ initials شخص?/- أ_م person_name/+ ه_و saudi_national_id/+
   mobileAlt phone_number/+ billingMailbox email_address/+ home_municipality city/+
   created_on date/+ contact_allowed boolean_flag/+ preference category/+ consignments_count count/+
   mail_stop location/+ comments free_text/?
  """),
  ("routeDepot", "logistics", 45, """
   yardSeq record_id/- location_label location/- subject_ref reference_id/-~pickWave
   handler_code business_identifier/- operator_shift duration_minutes/- reserved_slots count/-
   depot_cost price/- ledger_ccy currency_code/- open_for_sort boolean_flag/- route_group category/-
   bay_state status/- remarks free_text/- shape_blob geo_polygon/-
  """),
 ],
 "insurance": [
  ("وثائق_التغطية", "insurance", 227, """
   contractSeq record_id/- clientPointer reference_id/+@insuredDirectory عقد_ر policy_number/+
   risk_band risk_band/+ premium financial_amount/+ premium_ccy currency_code/- beginUTC date/+
   endUTC date/+ options category/+ active_flag boolean_flag/+ agreement_state status/+
   cover_limit financial_amount/+ agent_token business_identifier/-
  """),
  ("insuredDirectory", "customer", 149, """
   partySeq record_id/+ display_ص person_name/+ foreign_badge saudi_residency_id/+ hotline phone_number/+
   م_ب email_address/+ dateOfBirth date/+ household_city city/+ intake_region location/+
   is_minor boolean_flag/+ claim_count count/+ relationship_group category/+ aux_contact unknown/?
   identifiers_v2 business_identifier/-
  """),
  ("تسويات_المطالبات", "insurance", 438, """
   movementSeq record_id/- contractPointer reference_id/+@وثائق_التغطية claimant reference_id/+@insuredDirectory
   receivedAt date/+ projectedLoss financial_amount/+ amount_paid payment_amount/+ currency_tag currency_code/-
   adjudication status/+ decision_category category/+ logged_minutes duration_minutes/+ fraud_flag boolean_flag/+
   raw_note free_text/? statutory_ref regulatory_citation/-
  """),
  ("underwritingStaff", "workforce", 57, """
   staffSeq record_id/+ display_name person_name/+ directTel phone_number/+ external_iban saudi_iban/+
   wage_floor salary/+ cost_center department/- joinedUTC date/+ workload count/+ doc_minutes duration_minutes/+
   licensed_flag boolean_flag/+ grade_code job_title/+ desk_zone location/- internal_ref business_identifier/-
  """),
 ],
 "hospitality": [
  ("stayCalendar", "hospitality", 321, """
   roomStaySeq record_id/- profile_ref reference_id/+@guestRegistry unit_ref reference_id/-@roomStock
   itineraryKey reservation_code/+ checkinAt date/+ checkoutAt date/+ occupancy count/+
   overnight_status status/+ food_plan category/+ charge financial_amount/+ charge_ccy currency_code/-
   completed_flag boolean_flag/+ service_excerpt free_text/?
  """),
  ("guestRegistry", "hospitality", 186, """
   guestSeq record_id/+ الاسم_خ person_name/+ communicationSlot phone_number/+ invoice_to email_address/+
   ار_ه saudi_national_id/+ cityHome city/+ mailing_region location/+ tourist_group category/+
   member_since date/+ consent_flag boolean_flag/+ stays_count count/+ uninterpretable unknown/?
   facility_iqama business_identifier/-
  """),
  ("roomStock", "catalog", 81, """
   stockSeq record_id/- public_label service_name/- unit_serial service_code/- rack_rate price/-
   quoted_ccy currency_code/- hotelWing location/- beds count/- feature_class category/-
   sellable_flag boolean_flag/- revisedAt date/- turnover_minutes duration_minutes/-
   floor_markup room_layout/- unit_alias business_identifier/-
  """),
  ("folioDesk", "finance", 259, """
   deskSeq record_id/- stayPointer reference_id/+@stayCalendar tender_date date/+
   paid_total payment_amount/+ remit_state payment_status/+ denomination currency_code/-
   tender_kind payment_method/- reconciliation_minutes duration_minutes/- gratuity financial_amount/+
   voided_flag boolean_flag/- hub_code business_identifier/- tax_total tax_amount/+
   bank_routing saudi_iban/+
  """),
 ],
}
SEEDS = {"logistics": 715867, "insurance": 482971, "hospitality": 536257}
SECTOR_DOMAINS = {
    "currency_code": "finance", "payment_amount": "finance", "payment_status": "finance",
    "payment_method": "finance", "tax_amount": "finance", "saudi_iban": "finance",
    "salary": "workforce", "department": "workforce", "job_title": "workforce",
}


def fields(spec):
    pieces = iter(spec.split())
    for field, contract in zip(pieces, pieces, strict=True):
        kind, options = contract.split("/")
        personal = {"+": "yes", "-": "no", "?": "uncertain"}[options[0]]
        yield field, kind, personal, options[1:]


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def identity(prefix, n):
    stem = f"{prefix}{n % 10**8:08d}"
    score = sum(divmod(int(digit) * (2 if i % 2 == 0 else 1), 10)[0] +
                divmod(int(digit) * (2 if i % 2 == 0 else 1), 10)[1]
                for i, digit in enumerate(stem))
    # Deliberately unusable checksum.
    return stem + str((7 - score) % 10)


def draw(kind, i, rnd):
    x = rnd.random()
    if x < .035:
        return None
    seq = rnd.randrange(10**6, 99 * 10**6)
    if kind in {"saudi_national_id", "saudi_residency_id"}:
        return identity(1 if kind == "saudi_national_id" else 2, seq) if x < .90 else "unverified"
    if kind == "business_identifier":
        if x < .70:
            return identity(2 if i % 5 else 1, seq)
        return f"OBJ::{seq:07x}"
    if kind == "phone_number":
        return f"0096600{seq % 10**7:07d}" if x < .83 else "ext. pending"
    if kind == "email_address":
        return f"fake+{seq:08x}@holdout.invalid" if x < .9 else "missing@"
    if kind == "saudi_iban":
        return f"SA00{seq:020d}" if x < .85 else "test-only"
    if kind == "date":
        start = datetime(2021, 10, 11)
        day = start + timedelta(days=int(rnd.triangular(0, 1820, 780)), hours=rnd.randrange(24))
        return day.isoformat(timespec="seconds") if i % 4 else day.strftime("%d/%m/%Y")
    if kind in {"count", "duration_minutes"}:
        return int(rnd.expovariate(.07)) if i % 53 else -4
    if kind in {"price", "salary", "financial_amount", "payment_amount", "tax_amount"}:
        return round(rnd.lognormvariate(7 if kind == "salary" else 3.9, .65), 2)
    if kind in {"tracking_code", "policy_number", "reservation_code", "service_code"}:
        return {"tracking_code": "SHIP", "policy_number": "PLC", "reservation_code": "BK",
                "service_code": "UNIT"}[kind] + f"/{seq:09x}"
    if kind == "person_name":
        return rnd.choice(("Rana Fiction", "Samer Example", "ميس اختبار", "خالد تجريبي", "Huda Fixture"))
    if kind in {"city", "location"}:
        return rnd.choice(("Duba", "ضباء", "الرس", "Ar Rass", "AR RASS", " Duba "))
    if kind == "unknown":
        return rnd.choice(("??", "991B", "pending", "مزيج", "a@fake.invalid", "###", "2024-07-12"))
    if kind == "boolean_flag":
        return int(x > .25)
    payload = {
        "currency_code": ("SAR", "SAR", "AED", "BHD", "EUR"),
        "category": ("tier 01", "مسار خاص", "Standard", "STANDARD"),
        "status": ("confirmed", "محجوز", "Deferred"), "payment_status": ("Settled", "مؤجل", "Rejected"),
        "payment_method": ("cash", "wire", "voucher"), "department": ("Desk 1", "القسم ب", "Back Office"),
        "job_title": ("Agent Example", "موظف اختباري", "Night clerk"),
        "free_text": ("A fixture note. No real person is present.", "مدخل اختبار فقط.", "Action pending."),
        "service_name": ("Suite demo", "غرفة تجريبية", "Standard room fixture"),
        "geo_polygon": ("POLYGON((2 3,4 4,7 1,2 3))", "POINT(3 4)"),
        "risk_band": ("R-07", "F-A", "Rating beta"), "regulatory_citation": ("SIM-201.1a", "مو_٢"),
        "room_layout": ("L-shaped fixture", "room/A[010]"), "شخص?": ("X", "N/A", "لا يوجد"),
    }
    return rnd.choice(payload[kind])


def build(location, sector):
    specification = DATA[sector]
    tables = {table: (domain, count, list(fields(spec))) for table, domain, count, spec in specification}
    offsets = {table: 12000 + 73 * index for index, table in enumerate(tables)}
    truth = {}
    with sqlite3.connect(location) as db:
        for table, (domain, count, columns) in tables.items():
            truth[table] = {}
            definitions = []
            for name, kind, personal, link in columns:
                truth[table][name] = {"semantic_type": "unknown" if kind == "شخص?" else kind,
                                      "personal_data": personal, "domain": SECTOR_DOMAINS.get(kind, domain)}
                storage = ("INTEGER" if kind in {"record_id", "reference_id", "count", "duration_minutes", "boolean_flag"}
                           else "REAL" if kind in {"price", "salary", "financial_amount", "payment_amount", "tax_amount"}
                           else "TEXT")
                col = quote(name) + " " + storage
                if kind == "record_id":
                    col += " PRIMARY KEY"
                elif link.startswith("@"):
                    target = link[1:]
                    col += " REFERENCES " + quote(target) + "(" + quote(tables[target][2][0][0]) + ")"
                definitions.append(col)
            db.execute("CREATE TABLE " + quote(table) + "(" + ",".join(definitions) + ")")
            columns_data = []
            for index, (name, kind, _, link) in enumerate(columns):
                rnd = random.Random(SEEDS[sector] + index * 12_683 + offsets[table])
                records = []
                for i in range(count):
                    if kind == "record_id":
                        value = offsets[table] + i * 3
                    elif kind == "reference_id":
                        target = link[1:]
                        value = offsets[target] + 3 * rnd.randrange(tables[target][1])
                        if sector == "insurance" and i % 29 == 0 and index == 2:
                            value += 99999
                    else:
                        value = draw(kind, i, rnd)
                    records.append(value)
                columns_data.append(records)
            db.executemany("INSERT INTO " + quote(table) + " VALUES (" + ",".join("?" for _ in columns) + ")",
                           zip(*columns_data))
    return truth


def generate(root, engine_seal):
    if not engine_seal.is_file():
        raise ValueError("Seal the engine before generating the holdout.")
    root.mkdir(parents=True, exist_ok=False)
    (root / "databases").mkdir()
    (root / "labels").mkdir()
    for sector in DATA:
        truth = build(root / "databases" / (sector + ".sqlite"), sector)
        assert sum(map(len, truth.values())) == 52
        write(root / "labels" / (sector + ".json"), truth)
    write(root / "manifest.json", {
        "engine_seal_sha256": sha(engine_seal),
        "predefined_domain_mapping_sha256": sha(Path("evaluation/DOMAIN_SCORING.md")),
        "seeds": SEEDS,
        "files": {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.glob("*/*"))},
    })


if __name__ == "__main__":
    generate(Path("data/reliability/final"), Path("data/reliability/improved_seal.json"))
