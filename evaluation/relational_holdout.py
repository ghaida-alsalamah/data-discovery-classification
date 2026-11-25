"""Full-schema external holdouts with pre-inference, project-authored annotations."""
import argparse
import json
import sqlite3
from pathlib import Path
from subprocess import check_output

from evaluation.public_catalog import PERSONAL, LINKAGE, protocol_hashes, score
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read, rows_for
from evaluation.upstream_compare import run
from scripts.scan_data_asset import write_report

ROOT = Path("data/relational_validation")
LABELS = {
    "car_1": {
        "continents": ("geography", "ContId:record_id:N Continent:location:N"),
        "countries": ("geography", "CountryId:record_id:N CountryName:location:N Continent:reference_id:N"),
        "car_makers": ("vehicles", "Id:record_id:N Maker:organization_name:N FullName:organization_name:N Country:reference_id:N"),
        "model_list": ("vehicles", "ModelId:record_id:N Maker:reference_id:N Model:vehicle_model:N"),
        "car_names": ("vehicles", "MakeId:record_id:N Model:reference_id:N Make:vehicle_model:N"),
        "cars_data": ("vehicle_measurements", """Id:reference_id:N MPG:fuel_efficiency:N Cylinders:count:N
            Edispl:engine_displacement:N Horsepower:power:N Weight:mass:N Accelerate:acceleration:N Year:year:N"""),
    },
    "concert_singer": {
        "stadium": ("venues", """Stadium_ID:record_id:N Location:location:N Name:venue_name:N Capacity:count:N
           Highest:count:N Lowest:count:N Average:count:N"""),
        "singer": ("performers", """Singer_ID:record_id:L Name:person_name:D Country:location:L Song_Name:song_title:N
           Song_release_year:year:N Age:age:L Is_male:boolean_flag:L"""),
        "concert": ("concerts", "concert_ID:record_id:N concert_Name:event_title:N Theme:category:N Stadium_ID:reference_id:N Year:year:N"),
        "singer_in_concert": ("concerts", "concert_ID:reference_id:N Singer_ID:reference_id:L"),
    },
    "employee_hire_evaluation": {
        "employee": ("workforce", "Employee_ID:record_id:L Name:person_name:D Age:age:L City:city:L"),
        "shop": ("retail_operations", """Shop_ID:record_id:N Name:shop_name:N Location:location:N District:location:N
           Number_products:count:N Manager_name:person_name:D"""),
        "hiring": ("workforce", "Shop_ID:reference_id:N Employee_ID:reference_id:L Start_from:date:L Is_full_time:boolean_flag:L"),
        "evaluation": ("workforce", "Employee_ID:reference_id:L Year_awarded:year:L Bonus:salary:L"),
    },
    "northwind": {
        "Categories": ("catalog", "CategoryID:record_id:N CategoryName:category:N Description:free_text:N Picture:image:N"),
        "CustomerCustomerDemo": ("customer", "CustomerID:reference_id:U CustomerTypeID:reference_id:N"),
        "CustomerDemographics": ("customer", "CustomerTypeID:record_id:N CustomerDesc:free_text:N"),
        "Customers": ("customer", """CustomerID:record_id:U CompanyName:organization_name:N ContactName:person_name:D
            ContactTitle:job_title:L Address:location:U City:city:U Region:location:U PostalCode:postal_code:U
            Country:location:U Phone:phone_number:U Fax:fax_number:U"""),
        "Employees": ("workforce", """EmployeeID:record_id:L LastName:person_name:D FirstName:person_name:D Title:job_title:L
            TitleOfCourtesy:honorific:L BirthDate:date:L HireDate:date:L Address:location:L City:city:L Region:location:L
            PostalCode:postal_code:L Country:location:L HomePhone:phone_number:D Extension:phone_extension:L
            Photo:portrait:L Notes:free_text:L ReportsTo:reference_id:L PhotoPath:file_path:L"""),
        "EmployeeTerritories": ("workforce", "EmployeeID:reference_id:L TerritoryID:reference_id:N"),
        "Order Details": ("commerce", "OrderID:reference_id:L ProductID:reference_id:N UnitPrice:price:L Quantity:count:L Discount:discount_rate:L"),
        "Orders": ("commerce", """OrderID:record_id:N CustomerID:reference_id:U EmployeeID:reference_id:L OrderDate:date:L
            RequiredDate:date:L ShippedDate:date:L ShipVia:reference_id:N Freight:financial_amount:L ShipName:recipient_name:U
            ShipAddress:location:U ShipCity:city:U ShipRegion:location:U ShipPostalCode:postal_code:U ShipCountry:location:U"""),
        "Products": ("catalog", """ProductID:record_id:N ProductName:product_name:N SupplierID:reference_id:N CategoryID:reference_id:N
            QuantityPerUnit:package_size:N UnitPrice:price:N UnitsInStock:count:N UnitsOnOrder:count:N ReorderLevel:count:N Discontinued:boolean_flag:N"""),
        "Regions": ("geography", "RegionID:record_id:N RegionDescription:location:N"),
        "Shippers": ("logistics", "ShipperID:record_id:N CompanyName:organization_name:N Phone:phone_number:N"),
        "Suppliers": ("procurement", """SupplierID:record_id:N CompanyName:organization_name:N ContactName:person_name:D
            ContactTitle:job_title:L Address:location:U City:city:U Region:location:U PostalCode:postal_code:U
            Country:location:U Phone:phone_number:U Fax:fax_number:U HomePage:web_address:N"""),
        "Territories": ("geography", "TerritoryID:record_id:N TerritoryDescription:location:N RegionID:reference_id:N"),
    },
}


def configuration():
    return {
        "git": check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "backend": fingerprint(Path(".")),
        "protocol": {**protocol_hashes(), "relational_holdout": digest(Path(__file__))},
        "dictionary": None,
        "modes": ["evidence", "relational"],
    }


def freeze(root):
    seal = root / "holdout_seal.json"
    if seal.exists():
        raise FileExistsError(seal)
    inputs = {}
    for name, tables in LABELS.items():
        db = root / (name + ".sqlite")
        truth = {}
        for table, (domain, spec) in tables.items():
            truth[table] = {}
            for entry in spec.split():
                field, semantic, privacy = entry.split(":")
                truth[table][field] = {"semantic_type": semantic, "domain": domain,
                                       "personal_data": PERSONAL[privacy], "personal_linkage": LINKAGE[privacy]}
        with sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True) as conn:
            schema = {table: {r[1] for r in conn.execute("PRAGMA table_info(" + json.dumps(table) + ")")}
                      for table, in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if schema != {table: set(fields) for table, fields in truth.items()}:
            raise ValueError(f"Label coverage mismatch in {name}")
        output = root / (name + "_labels.json")
        write_report(output, truth)
        for path in (db, output):
            inputs[path.name] = digest(path)
    write_report(seal, {"configuration": configuration(), "inputs": inputs})


def evaluate(root):
    seal = read(root / "holdout_seal.json")

    def verify():
        if configuration() != seal["configuration"] or any(digest(root / file) != sha for file, sha in seal["inputs"].items()):
            raise ValueError("Frozen configuration or inputs have changed.")

    verify()
    paths = [root / (name + ".sqlite") for name in LABELS]
    for mode in seal["configuration"]["modes"]:
        run(mode, paths, root/mode)
    verify()
    metrics = {}
    for mode in seal["configuration"]["modes"]:
        cumulative, candidates, sectors = [], [], {}
        for db in paths:
            truth = read(root/(db.stem+"_labels.json"))
            report = read(root/mode/(db.stem+".json"))
            result = report["classifications"]
            rows = rows_for(db.stem, truth, result)
            entries = [(truth[r["table_name"]][r["column_name"]], r, {}) for r in result]
            cumulative.extend(rows)
            candidates.extend(entries)
            sectors[db.stem] = {**score(rows, entries, mode), "scan_seconds": report["timing_seconds"]["total"]}
        metrics[mode] = {"overall": score(cumulative, candidates, mode), "by_database": sectors}
    write_report(root/"metrics.json", metrics)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze","evaluate"))
    args = parser.parse_args()
    {"freeze": freeze, "evaluate": evaluate}[args.action](ROOT)
