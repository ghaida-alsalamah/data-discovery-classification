"""Independent fixtures and data dictionary. This module never imports the application."""
import argparse
import hashlib
import json
import random
import sqlite3
from shutil import copyfile
from datetime import date, timedelta
from pathlib import Path

# Each row declares name, semantic truth, personal status, name difficulty, and optional FK.
# A trailing domain override supports domains that vary within one table.
SCHEMAS = {
    "healthcare": {
        "مراجعي_العيادة": ("healthcare", """
            dossierKey record_id yes clear
            رمز_ه saudi_national_id yes ambiguous
            هاتف saudi_residency_id yes misleading
            archiveUnit phone_number yes misleading
            عنوان_بريد email_address yes ambiguous
            اسم_م person_name yes ambiguous
            placeOfCare city yes ambiguous
            residenceCity city yes clear
            تاريخ_م date yes ambiguous
            district_key location yes ambiguous
            contactBundle unknown yes ambiguous
            tissue_marker clinical_code yes clear
            risk_reading clinical_measurement yes clear
            consent_opt boolean_flag yes clear
        """),
        "encounterNotes": ("healthcare", """
            encounterPk record_id yes clear
            memberLink reference_id yes clear مراجعي_العيادة
            attending reference_id yes ambiguous careTeam
            appointment_day date yes clear
            release_day date yes clear
            triage_level category yes clear
            sleepMinutes duration_minutes yes clear
            episodeState status yes clear
            progress_notes free_text yes clear
            maskedEpisode unknown uncertain ambiguous
            diagnostic_group clinical_code yes clear
            sample_temp clinical_measurement yes clear
            queue_size count no clear
            transferDesk location no ambiguous
        """),
        "careTeam": ("workforce", """
            badgePk record_id yes clear
            preferred_name person_name yes clear
            رقم_ج phone_number yes ambiguous
            ward_mail email_address yes clear
            specialty category yes clear
            duty_station location no clear
            onboarding_day date yes clear
            base_wage salary yes clear
            shift_minutes duration_minutes yes clear
            licensed boolean_flag yes clear
            shiftVisits count yes clear
            contractState status yes clear
            compliance_note free_text yes clear
            vendor_national_id business_identifier no misleading domain=catalog
        """),
        "خدمات_المختبر": ("healthcare", """
            itemPk record_id no clear
            studyLabel service_name no clear
            رسم price no ambiguous
            denomination currency_code no clear domain=finance
            orderedUnits count no clear
            processMinutes duration_minutes no clear
            batch_ref business_identifier no ambiguous
            analyte clinical_code no clear
            deactivation date no clear
            panel_group category no clear
            availability boolean_flag no clear
            result_text free_text no clear
            labStatus status no clear
            v opaque_artifact no ambiguous
        """),
    },
    "ecommerce": {
        "orders": ("commerce", """
            orderPk record_id no clear
            buyer_ref reference_id yes clear accountsDirectory
            listing_ref reference_id no clear assortment
            orderDate date yes clear
            amount transaction_amount yes clear
            tax_portion tax_amount yes clear
            market currency_code no misleading domain=finance
            channel sales_channel no clear
            workflow status no clear
            pieceCount count no clear
            dispatched boolean_flag no clear
            fulfillment_city city yes clear
            cart_message free_text uncertain clear
            widget unknown uncertain ambiguous
        """),
        "accountsDirectory": ("customer", """
            partyPk record_id yes clear
            alias_display person_name yes ambiguous
            جوال_ع phone_number yes ambiguous
            البريد email_address yes clear
            locale city yes ambiguous
            معرف_ش saudi_national_id yes ambiguous
            travelPermit saudi_residency_id yes misleading
            activation_date date yes clear
            opt_in boolean_flag yes clear
            cohort category yes clear
            num_cases count yes clear
            profile_state status yes clear
            code_or_email unknown uncertain ambiguous
            goods_phone business_identifier no misleading domain=catalog
        """),
        "assortment": ("catalog", """
            offerPk record_id no clear
            listing_title service_name no clear
            ع_م service_code no ambiguous
            unit_fee price no clear
            codeISO currency_code no clear domain=finance
            product_family category no clear
            notes free_text no clear
            offered boolean_flag no clear
            warehouse_zone location no clear
            first_listed date no clear
            lag_min duration_minutes no clear
            unitStock count no clear
            account_email business_identifier no misleading
            picture_fingerprint opaque_artifact no clear
        """),
        "settlementJournal": ("finance", """
            entryPk record_id no clear
            source_ref reference_id yes clear orders
            debit payment_amount yes clear
            posting_day date yes clear
            currency currency_code no clear
            settlement_state payment_status yes clear
            tax_adjustment tax_amount yes clear
            payout_region saudi_iban yes misleading
            method payment_method no clear
            cleared boolean_flag no clear
            merchant_route business_identifier no ambiguous
            adjustment_note free_text uncertain clear
            fx_ratio exchange_ratio no clear
            keyhole unknown uncertain ambiguous
        """),
    },
    "education": {
        "دفتر_المتعلمين": ("education", """
            learnerPk record_id yes clear
            اسم_ط person_name yes ambiguous
            contactTag email_address yes ambiguous
            national_code business_identifier no misleading domain=operations
            ولي_ج phone_number yes ambiguous
            وصل_ه saudi_residency_id yes ambiguous
            تاريخ_ق date yes ambiguous
            enrollment_status status yes clear
            المستوى category yes clear
            homeArea city yes clear
            aidFlag boolean_flag yes clear
            credit_no count yes clear
            grade_band academic_grade yes clear
            comment free_text uncertain clear
        """),
        "course_units": ("education", """
            unitPk record_id no clear
            عنوان_و service_name no ambiguous
            unit_code service_code no clear
            hours_planned duration_minutes no clear
            cost_per_credit price no clear domain=finance
            cap_count count no clear
            is_remote boolean_flag no clear
            division category no clear
            public_summary free_text no clear
            campusZone location no clear
            accreditationState status no clear
            content_key business_identifier no ambiguous
            reading_level academic_grade no clear
            sync_blob opaque_artifact no clear
        """),
        "attendanceLog": ("education", """
            linePk record_id yes clear
            who reference_id yes ambiguous دفتر_المتعلمين
            what reference_id no ambiguous course_units
            markedAt date yes clear
            minutes_here duration_minutes yes clear
            missed_count count yes clear
            status status yes clear
            group_code category yes clear
            online boolean_flag yes clear
            workstation business_identifier no ambiguous domain=operations
            explanation free_text uncertain clear
            accessibility_marker clinical_code yes clear
            attendance_bonus academic_grade yes clear
            blobcol unknown uncertain ambiguous
        """),
        "staffDirectory": ("workforce", """
            facultyPk record_id yes clear
            حسن person_name yes ambiguous
            office_location location no clear
            phoneExt phone_number yes clear
            publicEmail email_address yes clear
            band salary yes ambiguous
            hiredOn date yes clear
            academic_role job_title yes clear
            unit_department department no clear
            active boolean_flag yes clear
            advisee_count count yes clear
            office_status status no clear
            bio free_text uncertain clear
            مص_ح saudi_iban yes ambiguous domain=finance
        """),
    },
}

SEEDS = {"healthcare": 91823, "ecommerce": 47051, "education": 68257}
ROWS = {"healthcare": (217, 361, 83, 37), "ecommerce": (383, 171, 92, 321),
        "education": (263, 67, 610, 73)}
CITY = ("الخبر", "Yanbu", "ينبع", "Khobar", "أبها", "Abha")
PEOPLE = ("Layla Fixture", "Mazen Placeholder", "دانا تجريبي", "بدر افتراضي", "Nadia Example")


def specs(sector):
    result = {}
    for table, (domain, lines) in SCHEMAS[sector].items():
        entries = []
        for line in lines.strip().splitlines():
            name, kind, personal, difficulty, *options = line.split()
            entries.append({
                "name": name, "semantic_type": kind, "personal_data": personal,
                "difficulty": difficulty, "domain": next(
                    (v.split("=")[1] for v in options if v.startswith("domain=")), domain),
                "references": next((v for v in options if "=" not in v), None),
            })
        result[table] = entries
    return result


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def invalid_id(prefix, number):
    stem = f"{prefix}{number:08d}"
    weighted = sum(((int(x) * 2 - 1) % 9 + 1 if int(x) else 0) if i % 2 == 0
                   else int(x) for i, x in enumerate(stem))
    return int(stem + str((3 - weighted) % 10))


def value(field, index, rng, seed, sizes, damage):
    kind = field["semantic_type"]
    if kind == "record_id":
        return index
    if kind == "reference_id":
        return sizes[field["references"]] + 99 if damage and index % 5 == 0 else (
            rng.randint(1, sizes[field["references"]]))
    if rng.random() < (.31 if damage and kind in {"date", "transaction_amount"} else .025):
        return None
    serial = (seed * 1000 + index * 37) % 100000000
    if kind in {"saudi_national_id", "saudi_residency_id"}:
        prefix = 1 if kind == "saudi_national_id" else 2
        return "مجهول" if index % 11 == 0 else str(invalid_id(prefix, serial))
    if kind == "phone_number":
        return "ext fixture" if index % 7 == 0 else "+96600" + f"{serial % 10**7:07d}"
    if kind == "email_address":
        return "invalid@@example.test" if index % 13 == 0 else f"fixture-{serial:x}@holdout.test"
    if kind == "saudi_iban":
        return "SA00" + f"{serial:020d}" if index % 9 else "INVALID-IBAN"
    if kind == "business_identifier":
        return invalid_id(2 if index % 3 else 1, serial)
    if kind == "date":
        if damage and index % 4 == 0:
            return "2040-02-31"
        day = date(2022, 7, 1) + timedelta(days=rng.randrange(820))
        return day.strftime("%d/%m/%Y") if index % 3 == 0 else day.isoformat()
    if kind in {"city", "location"}:
        return rng.choice(CITY + ((" KHOBAR ", "yanbu") if damage else ()))
    if kind == "person_name":
        return rng.choice(PEOPLE)
    if kind in {"financial_amount", "payment_amount", "transaction_amount", "price", "salary", "tax_amount"}:
        digits = rng.gammavariate(2.4, 70)
        return round(digits * (22 if kind == "salary" else .12 if kind == "tax_amount" else 1), 2)
    if kind in {"count", "duration_minutes"}:
        return -11 if damage and index % 5 == 0 else rng.randint(0, 110)
    values = {
        "boolean_flag": (0, 1), "service_code": (f"LAB_{serial % 1000:03d}", f"EDU_{index:03d}"),
        "service_name": ("رحلة افتراضية", "Fixture assessment", "دعم المختبر", "Practice unit"),
        "currency_code": ("SAR", "SAR", "AED", "EUR"), "status": ("مفتوح", "On hold", "Closed"),
        "payment_status": ("Received", "معلق", "Returned"), "payment_method": ("wire", "cash", "credit"),
        "sales_channel": ("kiosk", "web", "مباشر"), "category": ("Track A", "Track B", "مسار ج"),
        "department": ("قسم أ", "قسم ب", "Outreach"), "job_title": ("Trainer", "Support administrator"),
        "free_text": ("Fixture note with several words.", "تفاصيل اختبار صناعي فقط.", "No follow-up recorded."),
        "clinical_code": ("SIM.D4", "OBS-X13", "SAMPLE3"), "clinical_measurement": (36.5, 37.8, 39.1),
        "academic_grade": ("B+", "A-", "ناجح", "I"), "exchange_ratio": (0.257, 1.003, 4.174),
        "opaque_artifact": (b"\x08\x02\x00\x9d", b"\x03\x04\x0d\x80"),
        "unknown": ("??", "α⧗", "***", "مزيج", "test@example.test", "2023-03-28", str(serial)),
    }
    return rng.choice(values[kind])


def sql_type(field):
    kind = field["semantic_type"]
    if kind in {"record_id", "reference_id", "count", "duration_minutes", "boolean_flag", "business_identifier"}:
        return "INTEGER"
    if kind in {"payment_amount", "transaction_amount", "price", "salary", "tax_amount",
                "clinical_measurement", "exchange_ratio"}:
        return "REAL"
    return "BLOB" if kind == "opaque_artifact" else "TEXT"


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def create_database(path, sector, *, omit_listing_link=False):
    fields = specs(sector)
    sizes = dict(zip(fields, ROWS[sector]))
    rng = random.Random(SEEDS[sector])
    with sqlite3.connect(path) as connection:
        for table, columns in fields.items():
            definitions = []
            for field in columns:
                definition = f'{quote(field["name"])} {sql_type(field)}'
                target = field["references"]
                if field["semantic_type"] == "record_id":
                    definition += " PRIMARY KEY"
                elif target and not (
                    (sector == "education" and field["name"] == "what")
                    or (omit_listing_link and field["name"] == "listing_ref")
                ):
                    definition += f' REFERENCES {quote(target)}({quote(fields[target][0]["name"])})'
                definitions.append(definition)
            connection.execute(f'CREATE TABLE {quote(table)} ({", ".join(definitions)})')
        for table, columns in fields.items():
            rows = []
            for index in range(1, sizes[table] + 1):
                row = [value(field, index, rng, SEEDS[sector], sizes,
                             sector != "ecommerce" and index % 9 == 0)
                       for field in columns]
                rows.append(row)
            connection.executemany(
                f'INSERT INTO {quote(table)} VALUES ({", ".join("?" for _ in columns)})', rows)


def generate(output):
    output.mkdir(parents=True, exist_ok=False)
    labels = output / "labels"
    databases = output / "databases"
    labels.mkdir()
    databases.mkdir()
    manifest = {
        "seeds": SEEDS,
        "files": {},
        "design": "Independent schemas, synthetic values, labels authored before frozen inference.",
    }
    for sector in SCHEMAS:
        truth = labels / f"{sector}.json"
        write_json(truth, {table: {field["name"]: {k: v for k, v in field.items()
                                                 if k not in {"name", "references"}}
                                 for field in fields}
                           for table, fields in specs(sector).items()})
        create_database(databases / f"{sector}.sqlite", sector)
    stressed = databases / "ecommerce_stress.sqlite"
    copyfile(databases / "ecommerce.sqlite", stressed)
    with sqlite3.connect(stressed) as connection:
        connection.executescript("""
            UPDATE orders SET orderDate = NULL WHERE orderPk % 5 = 0;
            UPDATE orders SET orderDate = '2040-02-31' WHERE orderPk % 4 = 0 AND orderDate IS NOT NULL;
            UPDATE orders SET amount = NULL WHERE orderPk % 3 = 0;
            UPDATE orders SET listing_ref = 999999 WHERE orderPk % 5 = 0;
        """)
    create_database(databases / "ecommerce_unlinked.sqlite", "ecommerce", omit_listing_link=True)
    manifest["files"] = {path.relative_to(output).as_posix(): digest(path)
                         for directory in (labels, databases) for path in sorted(directory.iterdir())}
    write_json(output / "fixture_manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    generate(parser.parse_args().output)
