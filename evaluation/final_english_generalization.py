"""Generate a fixed, English-only final holdout. The scanner never reads this module."""
import json
import random
import sqlite3
from datetime import date, timedelta
from hashlib import file_digest
from pathlib import Path

ROOT = Path("data/final_english_generalization")
# name:type:privacy:value generator[:business domain]. D=direct, L=linked, N=nonpersonal, U=uncertain.
FIXTURE = {
    "property": (73409, {
        "occupant_roll": ("customer", """
            party_key:record_id:L:key display_line:person_name:D:name callback:phone_number:D:phone
            inbox_route:email_address:D:email civic_ref:saudi_national_id:D:citizen alien_file:saudi_residency_id:D:residency
            mailing_town:city:L:town enrolled:date:L:date contact_band:customer_segment:L:tier
            notices_ok:boolean_flag:L:flag access_token:business_identifier:N:object
            memo_line:free_text:U:memo locale_hint:category:L:language class_of_case:category:U:mixed
        """),
        "tenancy_agreements": ("property_management", """
            agreement_seq:record_id:N:key occupant_slot:reference_id:L:fk_occupant_roll
            unit_link:reference_id:N:fk_building_register begins:date:L:date lease_span:duration_minutes:L:lease_span
            occupancy_phase:status:L:lifecycle monthly_due:price:L:rent:finance cc:currency_code:N:currency:finance
            settlement_route:saudi_iban:D:iban:finance credit_actual:payment_amount:L:received:finance
            market_bucket:category:N:market contact_notes:free_text:U:memo parcel_signature:geo_polygon:N:polygon
            paper_form:unknown:U:mixed
        """),
        "building_register": ("property_management", """
            realty_seq:record_id:N:key contact_number:business_identifier:N:object handset:business_identifier:N:equipment
            street_block:location:N:street township:city:N:town rooms_count:count:N:rooms
            monthly_rate:price:N:rent:finance project_state:status:N:building_state
            dwelling_class:category:N:dwelling elevator_present:boolean_flag:N:flag
            commissioning_day:date:N:date dimensions:engineering_measure:N:dimension
            description_short:free_text:N:building_note service_area:service_region:N:region
        """),
    }),
    "food_production": (41813, {
        "production_runs": ("manufacturing", """
            run_seq:record_id:N:key machine_slot:reference_id:N:fk_equipment_register
            national_number:business_identifier:N:object trace_stamp:business_identifier:N:run_code
            shift_slot:category:N:shift item_units:count:N:units dwell_hrs:duration_minutes:N:minutes
            exit_state:status:N:run_state cleaning_done:boolean_flag:N:flag
            mix_design:recipe_formula:N:formula completed_day:date:N:date inspection_note:free_text:N:run_note
            staff_link:reference_id:L:fk_staff_roster:workforce output_mass:engineering_measure:N:mass
        """),
        "equipment_register": ("manufacturing", """
            equipment_seq:record_id:N:key serial_token:business_identifier:N:equipment
            installation_point:location:N:bay works_town:city:N:town
            upkeep_state:status:N:machine_state machine_family:category:N:machine installed:date:N:date
            next_check:date:N:other_date capacity_text:engineering_measure:N:dimension
            acquisition_cost:price:N:capital:finance currency_unit:currency_code:N:currency:finance
            remote_control:boolean_flag:N:flag technical_notes:free_text:N:machine_note stamp:unknown:U:mixed
        """),
        "staff_roster": ("workforce", """
            payroll_seq:record_id:L:key named_worker:person_name:D:name line_number:phone_number:D:phone
            electronic_contact:email_address:D:email work_authority:saudi_residency_id:D:residency
            payroll_account:saudi_iban:D:iban:finance compensation:salary:L:salary role_label:job_title:L:job
            cost_centre:department:L:department hired_at:date:L:date safety_certified:boolean_flag:L:flag
            rota_group:category:L:shift tool_badge:business_identifier:N:object town_of_residence:city:L:town
        """),
    }),
    "animal_care": (59627, {
        "keeper_contacts": ("customer", """
            keeper_seq:record_id:L:key print_as:person_name:D:name reach_out:email_address:D:email
            dial_path:phone_number:D:phone identity_document:saudi_national_id:D:citizen
            home_city:city:L:town started_on:date:L:date contact_method:category:L:channel
            consent_given:boolean_flag:L:flag account_tier:customer_segment:L:tier
            delivery_address:location:L:street enrolment_state:status:L:keeper_state
            caution_text:free_text:U:memo carrier_ref:business_identifier:N:equipment
        """),
        "animal_register": ("veterinary", """
            animal_seq:record_id:N:key custodian:reference_id:L:broken_keeper_contacts
            call_name:animal_name:N:animal_name chip_reference:business_identifier:N:object
            breed_group:category:N:breed animal_kind:category:N:species
            weight_at_intake:clinical_measurement:N:weight intake_stamp:date:N:date
            record_stage:status:N:animal_stage holding_location:location:N:bay
            badge_color:category:N:color care_instructions:free_text:U:animal_note
            clinic_town:city:N:town extra_payload:unknown:U:mixed
        """),
        "consultation_sessions": ("veterinary", """
            session_seq:record_id:N:key patient_locator:reference_id:N:fk_animal_register
            booking_contact:reference_id:L:fk_keeper_contacts examination_day:date:N:date
            wait_time:duration_minutes:N:minutes appointment_stage:status:N:consult_state
            treatment_notes:free_text:U:animal_note wallet_total:payment_amount:L:received:finance
            payment_flag:payment_status:L:payment_state:finance tax_piece:tax_amount:L:tax:finance
            money_unit:currency_code:N:currency:finance permit_key:business_identifier:N:object
            consultation_room:location:N:bay charges_locked:boolean_flag:N:flag:finance
        """),
    }),
}

TEXT = {
    "name": ("Avery Sample", "Jordan Fiction", "Casey Example", "Taylor Demo"),
    "town": ("Jazan", "Al Hofuf", "Riyadh", "Najran", "Tabuk"),
    "tier": ("Silver", "Family", "Priority"), "language": ("English", "French", "Spanish"),
    "market": ("Residential", "Retail", "Industrial"), "currency": ("SAR", "USD", "EUR"),
    "street": ("Cedar Avenue West", "Quarry Road", "Birch Lane", "Bridge Street"),
    "bay": ("Dock Seven", "East Loading Bay", "Intake Wing", "Suite Nine"),
    "region": ("Central Province", "Northern Zone", "Eastern Corridor"),
    "lifecycle": ("Renewal Offered", "Current", "Ending", "Terminated"),
    "building_state": ("Refurbishing", "Opened", "Decommissioned"),
    "run_state": ("Scrapped", "Finished", "Rework Requested", "On Hold"),
    "machine_state": ("Serviceable", "Isolated", "Awaiting Parts", "Retired"),
    "keeper_state": ("Enabled", "Archived", "Suspended"), "animal_stage": ("Fostered", "Rehomed", "Boarded"),
    "consult_state": ("No Show", "Checked In", "Seen", "Rescheduled"),
    "payment_state": ("Awaiting Transfer", "Credited", "Written Off", "Partially Paid"),
    "dwelling": ("Apartment", "Townhouse", "Studio"),
    "machine": ("Ribbon Blender", "Heat Exchanger", "Bottle Rinser"),
    "job": ("Mixing Supervisor", "Line Inspector", "Controls Technician"),
    "department": ("Packaging", "Quality Assurance", "Maintenance"),
    "shift": ("Early Shift", "Late Shift", "Overnight"),
    "channel": ("Postal Mail", "Text Message", "Voice Call"),
    "animal_name": ("Pippin", "Bracken", "Mallow", "Pebble"),
    "breed": ("Domestic Shorthair", "Mixed Breed", "Border Collie"),
    "species": ("Dog", "Cat", "Rabbit"), "color": ("Blue", "Green", "Amber"),
    "memo": ("Please send future reminders to the preferred contact channel.", "Access arrangements were confirmed after the visit."),
    "building_note": ("Exterior steps were rebuilt during the spring maintenance cycle.", "Use the secondary entrance during renovation."),
    "run_note": ("The batch was held until the laboratory released the inspection.", "The third pallet was moved to a separate bay."),
    "machine_note": ("Check the belt tension before restarting the unit.", "The spare assembly arrived after the scheduled service."),
    "animal_note": ("Offer a quiet waiting area before the examination.", "Monitor appetite for the next two days."),
    "mixed": ("", "Nineteen", "2024-10-09", "X-02", "To verify"),
    "formula": ("Oats 68 percent and honey 12 percent", "Flour 55 percent and water 31 percent"),
    "polygon": ("POLYGON((1 1, 2 1, 2 3, 1 1))", "POLYGON((0 0, 3 0, 1 1, 0 0))"),
}

def sa_id(prefix, serial, malformed):
    body = f"{prefix}{serial:08}"
    total = sum(sum(map(int, str(int(digit) * (2 - index % 2)))) for index, digit in enumerate(body))
    return body + str((-total + int(malformed)) % 10)

def sample(kind, i, seed, rng):
    serial = 90600000 + (seed * 37 + i * 17) % 99000
    if kind == "key":
        return 100 + i
    if kind.startswith("fk_") or kind.startswith("broken_"):
        if kind.startswith("broken_") and i == 17:
            return 999999
        return 100 + (i * 13 + seed) % 32
    if kind in {"citizen", "residency", "object"}:
        return sa_id(1 if kind != "residency" else 2, serial + (210000 if kind == "object" else 0), i % 11 == 0)
    if kind == "phone":
        return f"+9665{69130000 + (seed + i*97) % 100000:08}" if i % 11 else "+966-INVALID"
    if kind == "email":
        return f"fixture-{seed}-{i}@example.invalid" if i % 13 else "no-at-sign"
    if kind == "iban":
        body = f"76{seed*331+i*191:018}"
        check = 98 - int(body + "281000") % 97
        return f"SA{check if i % 11 else 0:02}{body}"
    if kind == "equipment":
        return f"05{(seed*733+i*1291)%100000000:08}"
    if kind == "run_code":
        return f"FG-{seed%100:02}-{i:04}"
    if kind in {"date", "other_date"}:
        return (date(2023, 5, 17) + timedelta(days=(seed + i * 29) % 900)).isoformat()
    if kind in {"rent", "received", "capital", "salary", "tax"}:
        base, spread = {"rent":(950,4500),"received":(65,900),"capital":(4600,50000),
                        "salary":(4200,18000),"tax":(12,250)}[kind]
        return round(base+rng.random()*spread,2)
    if kind in {"minutes", "lease_span", "units", "rooms", "mass", "dimension", "weight"}:
        base, spread = {"minutes":(9,155),"lease_span":(43200,520000),"units":(40,5400),"rooms":(1,8),
                        "mass":(160,1800),"dimension":(18,147),"weight":(2,49)}[kind]
        return base+rng.randrange(spread)
    if kind == "flag":
        return i % 3 != 0
    if kind in {"memo", "mixed", "animal_note"} and i % 7 == 0:
        return None
    return rng.choice(TEXT[kind])

def generate(root):
    root.mkdir(parents=True, exist_ok=False)
    files = {}
    for sector, (seed, tables) in FIXTURE.items():
        path = root / (sector + ".sqlite")
        truth = {}
        rng = random.Random(seed)
        with sqlite3.connect(path) as connection:
            for index, (table, (domain, spec)) in enumerate(tables.items()):
                columns = [item.split(":") for item in spec.split()]
                fields = []
                truth[table] = {}
                for name, kind, privacy, generator, *override in columns:
                    datatype = "TEXT"
                    if generator == "key":
                        datatype = "INTEGER PRIMARY KEY"
                    elif generator.startswith(("fk_", "broken_")):
                        target = generator.split("_",1)[1]
                        key = tables[target][1].split()[0].split(":")[0]
                        datatype = f"INTEGER REFERENCES {target}({key})"
                    elif generator in {"minutes","lease_span","units","rooms","mass","dimension","weight","flag"}:
                        datatype = "INTEGER"
                    elif generator in {"rent","received","capital","salary","tax"}:
                        datatype = "REAL"
                    fields.append(f"{name} {datatype}")
                    truth[table][name] = {"semantic_type":kind, "domain":override[0] if override else domain,
                                          "personal_linkage":{"D":"direct","L":"linked","N":"none","U":"uncertain"}[privacy],
                                          "personal_data":{"D":"yes","L":"yes","N":"no","U":"uncertain"}[privacy]}
                connection.execute(f"CREATE TABLE {table} (" + ", ".join(fields) + ")")
                for i in range(32):
                    connection.execute(f"INSERT INTO {table} VALUES (" + ",".join("?" for _ in fields) + ")",
                                       [sample(g, i, seed + index*101+j, rng) for j, (_, _, _, g, *_) in enumerate(columns)])
        labels = root / (sector + "_labels.json")
        labels.write_text(json.dumps(truth, indent=2)+"\n", encoding="utf-8")
        for artifact in (path, labels):
            with artifact.open("rb") as stream:
                files[artifact.name] = file_digest(stream, "sha256").hexdigest()
    (root/"manifest.json").write_text(json.dumps(files, indent=2)+"\n", encoding="utf-8")

if __name__ == "__main__":
    generate(ROOT)
