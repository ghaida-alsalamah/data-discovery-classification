"""Independent schema labels for the public Chinook and Sakila release fixtures."""
import argparse
import json
import sqlite3
from pathlib import Path

from evaluation.reliability_infer import digest
from evaluation.reliability_score import measured
from evaluation.score import binary, read, rows_for
from evaluation.upstream_compare import run
from evaluation.upstream_score import direct_report, direct_truth
from backend.app.classification.taxonomy import TYPES

ROOT = Path("data/external_validation")
PROTOCOL = (Path(__file__).resolve(), Path("scripts/scan_data_asset.py"),
            Path("evaluation/score.py"), Path("evaluation/reliability_score.py"),
            Path("evaluation/upstream_score.py"), Path("evaluation/upstream_compare.py"),
            Path(".models/minilm/tokenizer.json"), Path(".models/minilm/onnx/model.onnx"))


def protocol_hashes():
    return {p.name: digest(p) for p in PROTOCOL}
# table, business group, ordered native schema fields as name:type:privacy.
# L covers fields in an identifiable customer, worker, or activity record.
LABELS = {
    "chinook": {
        "Album": ("music_catalog", "AlbumId:record_id:N Title:album_title:N ArtistId:reference_id:N"),
        "Artist": ("music_catalog", "ArtistId:record_id:N Name:artist_name:U"),
        "Customer": ("customer", """CustomerId:record_id:L FirstName:person_name:D LastName:person_name:D
            Company:organization_name:N Address:location:L City:city:L State:location:L Country:location:L
            PostalCode:postal_code:L Phone:phone_number:D Fax:fax_number:D Email:email_address:D SupportRepId:reference_id:L"""),
        "Employee": ("workforce", """EmployeeId:record_id:L LastName:person_name:D FirstName:person_name:D
            Title:job_title:L ReportsTo:reference_id:L BirthDate:date:L HireDate:date:L Address:location:L City:city:L
            State:location:L Country:location:L PostalCode:postal_code:L Phone:phone_number:D Fax:fax_number:D Email:email_address:D"""),
        "Genre": ("music_catalog", "GenreId:record_id:N Name:category:N"),
        "Invoice": ("finance", """InvoiceId:record_id:N CustomerId:reference_id:L InvoiceDate:date:L BillingAddress:location:L
            BillingCity:city:L BillingState:location:L BillingCountry:location:L BillingPostalCode:postal_code:L Total:financial_amount:L"""),
        "InvoiceLine": ("finance", "InvoiceLineId:record_id:N InvoiceId:reference_id:L TrackId:reference_id:N UnitPrice:price:L Quantity:count:L"),
        "MediaType": ("music_catalog", "MediaTypeId:record_id:N Name:category:N"),
        "Playlist": ("music_catalog", "PlaylistId:record_id:N Name:playlist_title:N"),
        "PlaylistTrack": ("music_catalog", "PlaylistId:reference_id:N TrackId:reference_id:N"),
        "Track": ("music_catalog", """TrackId:record_id:N Name:track_title:N AlbumId:reference_id:N MediaTypeId:reference_id:N
            GenreId:reference_id:N Composer:credit_name:U Milliseconds:duration_milliseconds:N Bytes:byte_size:N UnitPrice:price:N"""),
    },
    "sakila": {
        "actor": ("film_catalog", "actor_id:record_id:L first_name:person_name:D last_name:person_name:D last_update:date:L"),
        "country": ("geography", "country_id:record_id:N country:location:N last_update:date:N"),
        "city": ("geography", "city_id:record_id:N city:city:N country_id:reference_id:N last_update:date:N"),
        "address": ("geography", """address_id:record_id:U address:location:U address2:location:U district:location:U
            city_id:reference_id:U postal_code:postal_code:U phone:phone_number:U last_update:date:U"""),
        "language": ("film_catalog", "language_id:record_id:N name:category:N last_update:date:N"),
        "category": ("film_catalog", "category_id:record_id:N name:category:N last_update:date:N"),
        "customer": ("customer", """customer_id:record_id:L store_id:reference_id:N first_name:person_name:D last_name:person_name:D
            email:email_address:D address_id:reference_id:L active:boolean_flag:L create_date:date:L last_update:date:L"""),
        "film": ("film_catalog", """film_id:record_id:N title:film_title:N description:free_text:N release_year:year:N
            language_id:reference_id:N original_language_id:reference_id:N rental_duration:duration_days:N rental_rate:price:N
            length:duration_minutes:N replacement_cost:price:N rating:category:N special_features:feature_list:N last_update:date:N"""),
        "film_actor": ("film_catalog", "actor_id:reference_id:L film_id:reference_id:N last_update:date:L"),
        "film_category": ("film_catalog", "film_id:reference_id:N category_id:reference_id:N last_update:date:N"),
        "film_text": ("film_catalog", "film_id:record_id:N title:film_title:N description:free_text:N"),
        "inventory": ("operations", "inventory_id:record_id:N film_id:reference_id:N store_id:reference_id:N last_update:date:N"),
        "staff": ("workforce", """staff_id:record_id:L first_name:person_name:D last_name:person_name:D address_id:reference_id:L
            picture:portrait:L email:email_address:D store_id:reference_id:N active:boolean_flag:L username:account_name:L
            password:credential:L last_update:date:L"""),
        "store": ("operations", "store_id:record_id:N manager_staff_id:reference_id:L address_id:reference_id:N last_update:date:N"),
        "payment": ("finance", """payment_id:record_id:N customer_id:reference_id:L staff_id:reference_id:L rental_id:reference_id:L
            amount:payment_amount:L payment_date:date:L last_update:date:L"""),
        "rental": ("commerce", """rental_id:record_id:N rental_date:date:L inventory_id:reference_id:N customer_id:reference_id:L
            return_date:date:L staff_id:reference_id:L last_update:date:L"""),
    },
}
LINKAGE = {"N": "none", "D": "direct", "L": "linked", "U": "uncertain"}
PERSONAL = {"N": "no", "D": "yes", "L": "yes", "U": "uncertain"}


def freeze(root):
    seal = root / "seal.json"
    if seal.exists():
        raise FileExistsError(seal)
    sakila = root / "sakila.sqlite"
    if not sakila.exists():
        with sqlite3.connect(sakila) as connection:
            for suffix in ("schema", "insert-data"):
                connection.executescript((root / f"sqlite-sakila-{suffix}.sql").read_text(encoding="utf-8-sig"))
    files = {}
    for name, tables in LABELS.items():
        db = root / (name + ".sqlite")
        if not db.is_file():
            raise FileNotFoundError(db)
        truth = {}
        for table, (domain, specification) in tables.items():
            truth[table] = {}
            for item in specification.split():
                field, kind, privacy = item.split(":")
                truth[table][field] = {"semantic_type": kind, "domain": domain, "personal_data": PERSONAL[privacy],
                                       "personal_linkage": LINKAGE[privacy]}
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            schema = {table: {column[1] for column in connection.execute("PRAGMA table_info(" + json.dumps(table) + ")")}
                      for table, in connection.execute(
                          "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if schema != {table: set(fields) for table, fields in truth.items()}:
            raise ValueError(f"Label coverage mismatch for {name}: {schema.keys() ^ truth.keys()}")
        labels = root / (name + "_labels.json")
        labels.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
        files.update({p.name: digest(p) for p in (db, labels)})
    from evaluation.reliability_infer import fingerprint
    from subprocess import check_output
    sha = check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    seal.write_text(json.dumps({"git": sha, "inputs": files, "backend": fingerprint(Path(".")),
                               "protocol": protocol_hashes()}, indent=2) + "\n", encoding="utf-8")


def grouping(rows):
    # B-cubed compares membership rather than the names of clusters.
    actual = {}
    predicted = {}
    membership = []
    for i, r in enumerate(rows):
        key = r["sector"], r["domain_true"]
        guess = r["sector"], r["domain_pred"] if r["domain_pred"] != "unknown" else i
        actual.setdefault(key, set()).add(i)
        predicted.setdefault(guess, set()).add(i)
        membership.append((key, guess))
    hits = [len(actual[key] & predicted[guess]) for key, guess in membership]
    precision = sum(hit / len(predicted[g]) for hit, (_, g) in zip(hits, membership)) / len(rows)
    recall = sum(hit / len(actual[k]) for hit, (k, _) in zip(hits, membership)) / len(rows)
    return {"precision":precision, "recall":recall, "f1":2*precision*recall/(precision+recall)}


def score(rows, entries, mode):
    data = measured(rows)
    supported = [r for r in rows if r["semantic_true"] in TYPES and r["semantic_true"] != "unknown"]
    unsupported = [r for r in rows if r["semantic_true"] not in TYPES]
    keep = ("fields", "strict_exact_accuracy", "broader_accuracy", "strict_domain_accuracy", "review_rate",
            "unreviewed_fields", "unreviewed_strict_semantic_accuracy", "unreviewed_joint_accuracy",
            "high_confidence_strict_error")
    return {**{k:data[k] for k in keep}, "grouping":grouping(rows),
            "supported_fields":len(supported),
            "supported_exact":sum(r["semantic_true"]==r["semantic_pred"] for r in supported)/len(supported) if supported else None,
            "unsupported_fields":len(unsupported),
            "unsupported_abstained":sum(r["semantic_pred"]=="unknown" for r in unsupported),
            "unreviewed_errors": data["unreviewed_errors"],
            "high_confidence_errors": data["confidence"]["confident_unreviewed_errors"],
            "direct":direct_report(entries, mode), "personal":data["personal"],
            "linked":binary([(direct_truth(t)=="linked",r["personal_linkage"]=="linked") for t,r,_ in entries
                             if direct_truth(t)!="uncertain"])}


def evaluate(root):
    from evaluation.reliability_infer import fingerprint
    from subprocess import check_output
    seal = read(root/"seal.json")
    def verify():
        if (any(digest(root/p)!=sha for p,sha in seal["inputs"].items())
                or fingerprint(Path(".")) != seal["backend"]
                or protocol_hashes() != seal["protocol"]
                or check_output(["git","rev-parse","HEAD"],text=True).strip()!=seal["git"]):
            raise ValueError("Frozen evaluation inputs changed.")
    verify()
    paths=[root/(name+".sqlite") for name in LABELS]
    for mode in ("english","evidence"):
        run(mode,paths,root/mode)
    verify()
    result={}
    for mode in ("english","evidence"):
        pooled, entries, sectors = [],[],{}
        for path in paths:
            name=path.stem
            truth=read(root/(name+"_labels.json"))
            fields=read(root/mode/(name+".json"))["classifications"]
            rows=rows_for(name,truth,fields)
            labels=[(truth[r["table_name"]][r["column_name"]],r,{}) for r in fields]
            pooled.extend(rows)
            entries.extend(labels)
            sectors[name]=score(rows,labels,mode)
        result[mode]={"overall":score(pooled,entries,mode),"sectors":sectors}
    (root/"metrics.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=("freeze","evaluate"))
    args=cli.parse_args()
    {"freeze":freeze,"evaluate":evaluate}[args.action](ROOT)
