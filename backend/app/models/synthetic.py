import json
import random
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from faker import Faker
from sqlalchemy import Column, Float, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy import URL, create_engine


def generate_database(path: Path, truth_path: Path, seed: int = 42):
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    metadata = MetaData()
    truth = {}

    def field(name, semantic, sql_type=String, personal=False, sensitivity="internal",
              issues=(), name_quality="clear", **kwargs):
        return (Column(name, sql_type, **kwargs), {
            "semantic_type": semantic, "personal_data": personal,
            "sensitivity": sensitivity, "quality_issues": list(issues),
            "column_name_quality": name_quality,
        })

    def key():
        return field("id", "record_id", Integer, primary_key=True)

    def fk(name, target, personal=False):
        column, label = field(name, "reference_id", Integer, personal, nullable=False)
        column.append_foreign_key(ForeignKey(f"{target}.id"))
        return column, label

    def table(name, domain, *fields):
        truth[name] = {column.name: {**label, "domain": domain} for column, label in fields}
        return Table(name, metadata, *(column for column, _ in fields))

    customers = table("customers", "customer", key(),
        field("full_name", "person_name", personal=True, issues=("duplicate",)),
        field("f01", "saudi_national_id", personal=True, sensitivity="restricted", name_quality="ambiguous",
              issues=("missing", "invalid_checksum"), unique=True),
        field("x2", "saudi_residency_id", personal=True, sensitivity="restricted", name_quality="ambiguous",
              issues=("missing", "invalid_checksum"), unique=True),
        field("attr_03", "phone_number", personal=True, name_quality="ambiguous",
              issues=("invalid_format", "unassigned_prefix")),
        field("email", "email_address", personal=True, issues=("missing",), unique=True),
        field("city", "city", personal=True, issues=("inconsistent_representation",)),
        field("segment", "customer_segment", personal=True),
        field("joined_on", "date", personal=True),
        field("active", "boolean_flag", Integer, personal=True))
    employees = table("employees", "workforce", key(),
        field("full_name", "person_name", personal=True),
        field("work_email", "email_address", personal=True, unique=True),
        field("department", "department"),
        field("title", "job_title", personal=True),
        field("salary_sar", "salary", Float, True, "restricted"),
        field("hire_date", "date", personal=True),
        field("office", "city"))
    services = table("services", "catalog", key(),
        field("ref_code", "service_code", unique=True, name_quality="ambiguous"),
        field("name_ar", "service_name"),
        field("name_en", "service_name"),
        field("category", "service_category"),
        field("monthly_fee_sar", "price", Float),
        field("currency", "currency_code"),
        field("available", "boolean_flag", Integer))
    transactions = table("transactions", "commerce", key(),
        fk("customer_id", "customers", True), fk("service_id", "services"),
        field("transaction_date", "date", personal=True),
        field("amount_sar", "transaction_amount", Float, True, "confidential"),
        field("tax_sar", "tax_amount", Float, True, "confidential"),
        field("channel", "sales_channel"), field("status", "transaction_status"))
    payments = table("payments", "finance", key(), fk("transaction_id", "transactions", True),
        field("region_code", "saudi_iban", personal=True, sensitivity="restricted", name_quality="misleading",
              issues=("missing", "invalid_format", "invalid_checksum")),
        field("amount_sar", "payment_amount", Float, True, "confidential"),
        field("currency", "currency_code"), field("method", "payment_method"),
        field("paid_on", "date", personal=True, issues=("missing",)),
        field("status", "payment_status"))
    tickets = table("support_tickets", "support", key(), fk("customer_id", "customers", True),
        fk("employee_id", "employees", True), fk("service_id", "services"),
        field("subject", "ticket_topic"), field("priority", "ticket_priority"),
        field("opened_on", "date", personal=True),
        field("closed_on", "date", personal=True, issues=("missing",)))
    usage = table("service_usage", "operations", key(), fk("customer_id", "customers", True),
        fk("service_id", "services"), field("usage_date", "date", personal=True),
        field("sessions", "session_count", Integer, True),
        field("minutes", "duration_minutes", Integer, True, issues=("out_of_range",)),
        field("device", "device_category", personal=True),
        field("region", "service_region", personal=True))

    def day(offset):
        return (date(2024, 1, 1) + timedelta(days=offset)).isoformat()

    def test_id(prefix, number):
        body = f"{prefix}{number:08d}"
        checksum = sum(sum(map(int, str(int(digit) * (2 if i % 2 == 0 else 1))))
                       for i, digit in enumerate(body))
        return body + str((1 - checksum) % 10)

    cities = ("Riyadh", "RIYADH", "الرياض", "Jeddah", "جدة", "الدمام")
    catalog = [
        ("Cloud Backup", "النسخ الاحتياطي", "cloud"),
        ("Digital Billing", "الفوترة الرقمية", "finance"),
        ("Business Mail", "بريد الأعمال", "communications"),
        ("Secure Storage", "التخزين الآمن", "cloud"),
        ("Online Booking", "الحجز الإلكتروني", "operations"),
        ("Analytics", "التحليلات", "operations"),
    ]
    customer_rows = [
        dict(id=i, full_name="نور مثال" if i % 4 == 0 else f"{fake.first_name()} Example",
             f01=None if i % 2 else test_id(1, i),
             x2=test_id(2, i) if i % 2 else None,
             attr_03="bad-number" if i % 29 == 0 else f"+96600{i:07d}",
             email=None if i % 17 == 0 else f"customer{i}@example.test",
             city=rng.choice(cities), segment=rng.choice(("individual", "business")),
             joined_on=day(rng.randrange(365)), active=int(i % 9 != 0))
        for i in range(1, 1001)
    ]
    employee_rows = [
        dict(id=i, full_name=f"{fake.first_name()} Sample", work_email=f"staff{i}@example.test",
             department=rng.choice(("Operations", "الدعم", "Finance")), title="Analyst",
             salary_sar=rng.randrange(6000, 23000), hire_date=day(-rng.randrange(720)),
             office=rng.choice(cities))
        for i in range(1, 61)
    ]
    service_rows = [
        dict(id=i, ref_code=f"SVC-{i:03d}", name_ar=ar, name_en=en, category=category,
             monthly_fee_sar=15 * i, currency="SAR", available=1)
        for i, (en, ar, category) in enumerate(catalog, 1)
    ]
    transaction_rows = []
    payment_rows = []
    for i in range(1, 2401):
        service = rng.choice(service_rows)
        amount = service["monthly_fee_sar"]
        paid = i % 12 != 0
        transacted = day(rng.randrange(365, 730))
        transaction_rows.append(dict(
            id=i, customer_id=(i - 1) % 1000 + 1, service_id=service["id"],
            transaction_date=transacted, amount_sar=amount, tax_sar=round(amount * .15, 2),
            channel=rng.choice(("web", "app", "partner")), status="settled" if paid else "pending"))
        method = "transfer" if i % 3 == 0 else "card"
        # Check digits 00 and bank code 00 keep these placeholders unusable.
        iban = "SA00" + f"{i:020d}" if method == "transfer" else None
        payment_rows.append(dict(
            id=i, transaction_id=i, region_code="bad-iban" if i % 71 == 0 else iban,
            amount_sar=round(amount * 1.15, 2), currency="SAR", method=method,
            paid_on=transacted if paid else None, status="paid" if paid else "pending"))
    ticket_rows = [
        dict(id=i, customer_id=rng.randint(1, 1000), employee_id=rng.randint(1, 60),
             service_id=rng.randint(1, len(catalog)), subject=rng.choice(("Login", "الفاتورة")),
             priority=rng.choice(("low", "normal", "high")), opened_on=day(365 + i),
             closed_on=day(368 + i) if i % 5 else None)
        for i in range(1, 351)
    ]
    usage_rows = [
        dict(id=i, customer_id=rng.randint(1, 1000), service_id=rng.randint(1, len(catalog)),
             usage_date=day(rng.randrange(365, 730)), sessions=rng.randint(1, 20),
             minutes=-1 if i % 113 == 0 else rng.randint(1, 300),
             device=rng.choice(("mobile", "desktop")), region=rng.choice(("central", "west", "east")))
        for i in range(1, 3001)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as staging:
        staged_db = Path(staging) / "source.sqlite"
        staged_truth = Path(staging) / "ground_truth.json"
        engine = create_engine(URL.create("sqlite", database=str(staged_db)), hide_parameters=True)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys = ON")
                metadata.create_all(connection)
                for source, rows in ((customers, customer_rows), (employees, employee_rows),
                                     (services, service_rows), (transactions, transaction_rows),
                                     (payments, payment_rows), (tickets, ticket_rows), (usage, usage_rows)):
                    connection.execute(source.insert(), rows)
        finally:
            engine.dispose()
        staged_truth.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged_db.replace(path)
        staged_truth.replace(truth_path)
