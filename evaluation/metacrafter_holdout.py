"""Independent fresh synthetic benchmark. No classification or prior fixture imports."""
import hashlib
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# Field, semantic truth, personal status, optional reference target.
CATALOG = {
    "utilities": [
        ("plantAssets", "operations", "asset_seq:record_id:n meter_token:business_identifier:n "
         "محطة:location:n power_readout:electrical_measurement:n installed_day:date:n voltage_group:category:n "
         "vendor_phone:business_identifier:n feeder_count:count:n live_flag:boolean_flag:n extra_blob:unknown:u"),
        ("gridMaintenance", "operations", "job_no:record_id:n plant_ref:reference_id:n:plantAssets "
         "dispatch_day:date:n work_minutes:duration_minutes:n episode_status:status:n team_note:free_text:u "
         "charge_amt:financial_amount:n ISO_unit:currency_code:n work_ref:business_identifier:n event_slug:unknown:u"),
        ("fieldStaff", "workforce", "badge_seq:record_id:y اسم_ع:person_name:y directline:phone_number:y "
         "entry_token:saudi_residency_id:y service_email:email_address:y تم_ق:date:y pay_grade:salary:y "
         "team_section:department:n assigned_area:city:y credentials_current:boolean_flag:y"),
    ],
    "procurement": [
        ("supplierOffers", "commerce", "offer_seq:record_id:n company_code:business_identifier:n "
         "classification_code:procurement_code:n quote_amt:price:n bid_ccy:currency_code:n "
         "submitted_date:date:n origin_city:city:n catalog_label:service_name:n "
         "sealed_flag:boolean_flag:n notes_public:free_text:u"),
        ("ledgerDisbursements", "finance", "step_seq:record_id:n offer_reference:reference_id:n:supplierOffers "
         "payable_amt:payment_amount:n applied_tax:tax_amount:n nation_ref:business_identifier:n "
         "cleared_date:date:n payout_iban:saudi_iban:y remit_status:payment_status:n "
         "قناة_د:payment_method:n payload_variant:unknown:u"),
        ("liaisonDirectory", "customer", "contact_seq:record_id:y given_display:person_name:y "
         "رقم_ت:phone_number:y mailbox_public:email_address:y مرجع_ه:saudi_national_id:y "
         "city_pref:city:y date_joined:date:y phone_port:business_identifier:n "
         "optout:boolean_flag:y meeting_count:count:y"),
    ],
    "community": [
        ("volunteerRoster", "community", "vol_seq:record_id:y ism_short:person_name:y ت_ج:phone_number:y "
         "contact_alias:email_address:y tag_renewal:saudi_residency_id:y الرمز_ب:city:y "
         "enrolled_at:date:y waivered:boolean_flag:y affinity:category:y badge_rfid:business_identifier:n"),
        ("دورات_الخدمة", "community", "session_seq:record_id:n volunteer_ptr:reference_id:y:volunteerRoster "
         "shift_day:date:y location_hint:location:y people_count:count:y "
         "hrs_minutes:duration_minutes:y check_status:status:y program_type:category:n "
         "feedback_free:free_text:u activity_shape:geo_polygon:n"),
        ("partnerDirectory", "support", "partner_seq:record_id:n host_ptr:reference_id:n:دورات_الخدمة "
         "site_title:service_name:n org_reg_id:business_identifier:n help_mail:email_address:y "
         "support_notes:free_text:u city_center:city:n category:category:n "
         "partner_active:boolean_flag:n ambiguity_mix:unknown:u"),
    ],
}
SEEDS = dict(utilities=576401, procurement=329813, community=748529)
PERSON = {"y": "yes", "n": "no", "u": "uncertain"}


def quote(text):
    return '"' + text.replace('"', '""') + '"'


def values(kind, n, rng):
    if rng.randrange(28) == 0:
        return None
    seq = rng.randrange(10**7, 10**8)
    if kind in {"business_identifier", "saudi_residency_id", "saudi_national_id"}:
        if kind == "business_identifier" and n % 7 == 0:
            return f"BIZ-{seq:X}"
        prefix = 1 if kind == "saudi_national_id" else 2
        digits = str(prefix) + str(seq)
        checksum = sum(sum(divmod(int(ch) * (2 if i % 2 == 0 else 1), 10))
                       for i, ch in enumerate(digits))
        return digits + str((4 - checksum) % 10) if n % 13 else "unverified"
    if kind == "email_address":
        return f"discovery-{seq:x}@demo.invalid" if n % 8 else "bad@"
    if kind == "phone_number":
        return f"+96600{seq % 10**7:07d}" if n % 7 else "fixture extension"
    if kind == "saudi_iban":
        return f"SA00{seq:020d}"
    if kind == "date":
        if n % 29 == 0:
            return "2039-02-30"
        day = date(2020, 3, 8) + timedelta(days=rng.randrange(1500))
        return day.isoformat() if n % 2 else day.strftime("%d/%m/%Y")
    if kind in {"count", "duration_minutes"}:
        return rng.randint(1, 80) if n % 37 else -3
    if kind in {"financial_amount", "payment_amount", "tax_amount", "salary", "price", "electrical_measurement"}:
        return round(rng.gammavariate(2, 30) * (100 if kind == "salary" else 1), 2)
    if kind == "boolean_flag":
        return int(rng.random() > .30)
    return rng.choice({
        "location": ("Umluj", "أملج", "Sakaka", "سكاكا"),
        "city": ("Umluj", "UMLUJ", "أملج", "Sakaka", "سكاكا"),
        "currency_code": ("SAR", "AED", "SAR", "EUR"),
        "category": ("Dispatch A", "Track B", "مسار ج"),
        "status": ("On hold", "معلق", "Closed"),
        "payment_status": ("Cleared", "Pending", "مؤجل"),
        "payment_method": ("cash", "wire", "voucher"),
        "service_name": ("Practice supply pack", "خدمة تجريبية", "Demo station"),
        "person_name": ("Hala Fiction", "Bader Demo", "منى اختبار", "وليد تجريبي"),
        "department": ("Desk A", "القسم ب", "Maintenance"),
        "unknown": ("00", "test@example.invalid", "@@", "مزيج", "2026-02-12", "none"),
        "free_text": ("Fixture note without names.", "بيان صناعي فقط.", "Review requested."),
        "procurement_code": ("PRC.A21", "RFP-C2", "SIM.A.14"),
        "geo_polygon": ("POLYGON((1 2,3 4,1 2))", "POINT(1 2)"),
    }[kind])


def build(sector, db_path):
    rng = random.Random(SEEDS[sector])
    schema = {table: (domain, [part.split(":") for part in spec.split()])
              for table, domain, spec in CATALOG[sector]}
    row_keys = {table: sorted(rng.sample(range(500, 17000), 137 + index * 79))
                for index, table in enumerate(schema)}
    labels = {}
    with sqlite3.connect(db_path) as db:
        for table, (domain, fields) in schema.items():
            labels[table] = {}
            definitions = []
            for name, kind, pii, *ref in fields:
                labels[table][name] = {"semantic_type": kind, "personal_data": PERSON[pii],
                                       "domain": "finance" if kind in {"currency_code", "saudi_iban", "tax_amount"}
                                       else domain}
                affin = ("INTEGER" if kind in {"record_id", "reference_id", "boolean_flag", "count", "duration_minutes"}
                         else "REAL" if kind.endswith("amount") or kind in {"price", "salary", "electrical_measurement"}
                         else "TEXT")
                definition = f"{quote(name)} {affin}"
                if kind == "record_id":
                    definition += " PRIMARY KEY"
                if ref:
                    definition += " REFERENCES " + quote(ref[0]) + "(" + quote(schema[ref[0]][1][0][0]) + ")"
                definitions.append(definition)
            db.execute("CREATE TABLE " + quote(table) + "(" + ",".join(definitions) + ")")
            for n, key in enumerate(row_keys[table], 1):
                record = [key if kind == "record_id" else
                          (999999 if table == "partnerDirectory" and n % 23 == 0 else rng.choice(row_keys[ref[0]]))
                          if ref else values(kind, n, rng)
                          for _, kind, _, *ref in fields]
                db.execute("INSERT INTO " + quote(table) + " VALUES (" + ",".join("?" for _ in record) + ")", record)
    return labels


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    root = Path("data/metacrafter/fresh")
    seal = root.parent / "experiment_seal.json"
    if not seal.is_file():
        raise ValueError("Seal the experiment first.")
    root.mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "databases").mkdir()
    for sector in CATALOG:
        labels = build(sector, root / "databases" / f"{sector}.sqlite")
        assert sum(map(len, labels.values())) == 30
        write(root / "labels" / f"{sector}.json", labels)
    write(root / "manifest.json", {"experiment_seal": sha(seal), "seeds": SEEDS,
                                  "files": {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.glob("*/*"))}})


if __name__ == "__main__":
    main()
