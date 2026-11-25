"""Fresh synthetic relational fixtures derived from public schema definitions."""
from datetime import date, timedelta
from random import Random
import re
import sqlite3

from evaluation.reliability_infer import digest
from evaluation.public_catalog import LINKAGE, PERSONAL
from scripts.scan_data_asset import write_report

SOURCES = {
    "customer_deliveries": (71271, {
        "Products": ("product_catalog", "product_id:record_id:N product_name:product_name:N product_price:price:N product_description:free_text:N"),
        "Addresses": ("address_book", """address_id:record_id:U address_details:location:U city:city:U
            zip_postcode:postal_code:U state_province_county:location:U country:location:U"""),
        "Customers": ("customer_accounts", """customer_id:record_id:L payment_method:payment_method:L
            customer_name:person_name:D customer_phone:phone_number:D customer_email:email_address:D
            date_became_customer:date:L"""),
        "Regular_Orders": ("commerce", "regular_order_id:record_id:N distributer_id:reference_id:L"),
        "Regular_Order_Products": ("commerce", "regular_order_id:reference_id:L product_id:reference_id:N"),
        "Actual_Orders": ("commerce", "actual_order_id:record_id:N order_status_code:status:L regular_order_id:reference_id:L actual_order_date:date:L"),
        "Actual_Order_Products": ("commerce", "actual_order_id:reference_id:L product_id:reference_id:N"),
        "Customer_Addresses": ("customer_accounts", "customer_id:reference_id:L address_id:reference_id:L date_from:date:L address_type:category:L date_to:date:L"),
        "Delivery_Routes": ("routing", "route_id:record_id:N route_name:route_name:N other_route_details:free_text:N"),
        "Delivery_Route_Locations": ("routing", "location_code:record_id:N route_id:reference_id:N location_address_id:reference_id:N location_name:location:N"),
        "Trucks": ("fleet_assets", "truck_id:record_id:N truck_licence_number:license_plate:N truck_details:free_text:N"),
        "Employees": ("workforce", "employee_id:record_id:L employee_address_id:reference_id:L employee_name:person_name:D employee_phone:phone_number:D"),
        "Order_Deliveries": ("dispatch", """location_code:reference_id:N actual_order_id:reference_id:L
            delivery_status_code:status:L driver_employee_id:reference_id:L truck_id:reference_id:N delivery_date:date:L"""),
    }),
    "insurance_and_eClaims": (82463, {
        "Customers": ("policyholders", "Customer_ID:record_id:L Customer_Details:free_text:L"),
        "Staff": ("workforce", "Staff_ID:record_id:L Staff_Details:free_text:L"),
        "Policies": ("insurance_policies", "Policy_ID:record_id:N Customer_ID:reference_id:L Policy_Type_Code:category:L Start_Date:date:L End_Date:date:L"),
        "Claim_Headers": ("claims", """Claim_Header_ID:record_id:N Claim_Status_Code:status:L Claim_Type_Code:category:L
            Policy_ID:reference_id:L Date_of_Claim:date:L Date_of_Settlement:date:L Amount_Claimed:financial_amount:L Amount_Piad:financial_amount:L"""),
        "Claims_Documents": ("claims", "Claim_ID:reference_id:L Document_Type_Code:category:L Created_by_Staff_ID:reference_id:L Created_Date:date:L"),
        "Claims_Processing_Stages": ("claims_reference", "Claim_Stage_ID:record_id:N Next_Claim_Stage_ID:reference_id:N Claim_Status_Name:status:N Claim_Status_Description:free_text:N"),
        "Claims_Processing": ("claims", "Claim_Processing_ID:record_id:N Claim_ID:reference_id:L Claim_Outcome_Code:status:L Claim_Stage_ID:reference_id:N Staff_ID:reference_id:L"),
    }),
    "product_catalog": (19619, {
        "Attribute_Definitions": ("catalog_metadata", "attribute_id:record_id:N attribute_name:attribute_name:N attribute_data_type:data_type:N"),
        "Catalogs": ("catalog_metadata", "catalog_id:record_id:N catalog_name:catalog_name:N catalog_publisher:organization_name:N date_of_publication:date:N date_of_latest_revision:date:N"),
        "Catalog_Structure": ("catalog_metadata", "catalog_level_number:record_id:N catalog_id:reference_id:N catalog_level_name:category:N"),
        "Catalog_Contents": ("inventory", """catalog_entry_id:record_id:N catalog_level_number:reference_id:N parent_entry_id:reference_id:N
            previous_entry_id:reference_id:N next_entry_id:reference_id:N catalog_entry_name:product_name:N product_stock_number:business_identifier:N
            price_in_dollars:price:N price_in_euros:price:N price_in_pounds:price:N capacity:capacity:N length:distance:N height:distance:N width:distance:N"""),
        "Catalog_Contents_Additional_Attributes": ("inventory", "catalog_entry_id:reference_id:N catalog_level_number:reference_id:N attribute_id:reference_id:N attribute_value:unknown:N"),
    }),
    "station_weather": (38711, {
        "train": ("rail_services", "id:record_id:N train_number:business_identifier:N name:train_name:N origin:location:N destination:location:N time:time_of_day:N interval:duration_minutes:N"),
        "station": ("stations", "id:record_id:N network_name:organization_name:N services:category:N local_authority:organization_name:N"),
        "route": ("rail_services", "train_id:reference_id:N station_id:reference_id:N"),
        "weekly_weather": ("weather", "station_id:reference_id:N day_of_week:day_of_week:N high_temperature:temperature:N low_temperature:temperature:N precipitation:precipitation:N wind_speed_mph:speed:N"),
    }),
}
NAMES = ("Noah Fenwright", "Lara Westbrine", "Tariq Nobleheld", "Maria Firbank",
         "Loren Caldwell", "Rania Stonewick", "Jordan Whitley", "Mina Blakemere",
         "Evan Jarrow", "Tess Oakford", "Oscar Hillwick", "Nadia Brumley")
TOWNS = ("Bath", "Reading", "Carlisle", "York", "Exeter", "Bristol")
PLACES = ("Barnard County", "Northgate District", "Redwood Station", "Brightwater Parish")
PARAGRAPHS = (
    "The document entered the scheduled review queue after the required checks were complete.",
    "The supporting record was revised on a later cycle after the initial entry was returned.",
    "Staff verified the source information and scheduled the remaining review for the next cycle.",
)
RANGES = {"price": (1, 170), "financial_amount": (100, 6000), "capacity": (1, 500),
          "distance": (2, 80), "temperature": (-4, 29), "precipitation": (0, 20), "speed": (3, 75)}
ROWS = 24


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def open_ro(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def value(kind, name, index, random):
    if kind == "record_id" or kind == "reference_id":
        return 3100 + index
    if kind == "person_name":
        return random.choice(NAMES)
    if kind == "email_address":
        return "contact." + str(index) + "@example.org"
    if kind == "phone_number":
        tail = 100 + index
        return f"+1 202 555 {tail:04}" if index % 10 else "pending extension"
    if kind == "date":
        return (date(2021, 4, 18) + timedelta(days=random.randrange(1200))).isoformat()
    if kind == "time_of_day":
        return f"{6 + index % 15:02}:{15 * (index % 4):02}:00"
    if kind in RANGES:
        return round(random.uniform(*RANGES[kind]), 2)
    if kind == "duration_minutes":
        return random.randrange(10, 90, 5)
    if kind == "postal_code":
        return random.choice(("B7 5DU", "EH7 4NZ", "KT7 0LF", "OX4 2AA"))
    if kind == "business_identifier":
        return f"BX-{random.randrange(100000, 240000)}"
    if kind == "license_plate":
        return f"XX{index:02} ZYX"
    if kind == "product_name":
        return random.choice(("Folding rack", "Steel latch", "Shipping container", "Heat seal strip"))
    if kind == "location":
        if "address" in name.lower():
            return f"{100 + index} Example Orchard Lane"
        return random.choice(PLACES)
    return random.choice({
        "status": ("Pending", "In progress", "Settled", "Closed"),
        "category": ("Primary", "Secondary", "Standard", "Express"),
        "day_of_week": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        "city": TOWNS, "free_text": PARAGRAPHS,
        "payment_method": ("Card", "Bank transfer", "Invoice"),
        "route_name": ("Northern Circuit", "Central Loop", "Shoreline Route"),
        "train_name": ("River Local", "Regional Express", "Early Shuttle"),
        "attribute_name": ("Weight", "Color", "Grade", "Packaging size"),
        "data_type": ("Character", "Integer", "Measurement"),
        "catalog_name": ("Industrial inventory", "Equipment trade list", "Commercial materials"),
        "organization_name": ("Redwater Transit Authority", "Weldmere Distribution", "Baywood Equipment"),
        "unknown": ("Bucket A", "2.3", "Flag pending", "56", "Not supplied"),
    }[kind])


def materialize(root):
    files = {}
    for source, (seed, tables) in SOURCES.items():
        path = root / (source + ".sqlite")
        template = root / "schema_sources" / (source + ".sqlite")
        if path.exists():
            raise FileExistsError(path)
        truth = {
            table: {field: {"semantic_type": kind, "domain": group, "personal_data": PERSONAL[privacy],
                            "personal_linkage": LINKAGE[privacy]}
                    for field, kind, privacy in (item.split(":") for item in spec.split())}
            for table, (group, spec) in tables.items()
        }
        random = Random(seed)
        with open_ro(template) as public, sqlite3.connect(path) as db:
            metadata = {
                table: list(public.execute("PRAGMA table_info(" + quote(table) + ")"))
                for table in truth
            }
            for table, expected in truth.items():
                columns = metadata[table]
                if {c[1] for c in columns} != set(expected):
                    raise ValueError(f"Unexpected source schema for {source}.{table}.")
                declarations = []
                for _, name, dtype, _, _, _ in columns:
                    if not re.fullmatch(r"[A-Za-z0-9_ (),.]*", dtype):
                        raise ValueError("Unexpected declared source type.")
                    declarations.append(quote(name) + " " + dtype)
                primary = [c[1] for c in sorted(columns, key=lambda item: item[5]) if c[5]]
                if primary:
                    declarations.append("PRIMARY KEY (" + ", ".join(map(quote, primary)) + ")")
                edges = {}
                for group, _, target, field, dest, *_ in public.execute("PRAGMA foreign_key_list(" + quote(table) + ")"):
                    edges.setdefault((group, target), []).append((field, dest))
                for (_, target), edge in edges.items():
                    if target not in truth or any(dest is None for _, dest in edge):
                        raise ValueError("Unexpected constraint in source schema.")
                    declarations.append("FOREIGN KEY (" + ", ".join(quote(a) for a, _ in edge)
                                        + ") REFERENCES " + quote(target) + " (" + ", ".join(quote(b) for _, b in edge) + ")")
                db.execute("CREATE TABLE " + quote(table) + "(" + ", ".join(declarations) + ")")
                for index in range(ROWS):
                    kinds = {c[1]: expected[c[1]]["semantic_type"] for c in columns}
                    slots = {c[1]: value(kinds[c[1]], c[1], index, random) for c in columns}
                    for (_, target), edge in edges.items():
                        for field, destination in edge:
                            if truth[target][destination]["semantic_type"] in {"record_id", "reference_id"}:
                                slots[field] = 3100 + index
                    db.execute("INSERT INTO " + quote(table) + " VALUES (" + ",".join("?" for _ in columns) + ")",
                               [slots[c[1]] for c in columns])
        labels = root / (source + "_labels.json")
        write_report(labels, truth)
        for item in (path, labels, root / (source + ".source"), template):
            files[item.relative_to(root).as_posix()] = digest(item)
    return files
