"""Evaluate the local open catalog on four unused public relational schemas."""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from subprocess import check_output
from time import perf_counter

from backend.app.classification.local_llm import launch, peak_memory
from backend.app.classification.open_catalog import EXTENSIONS
from backend.app.classification.taxonomy import TYPES
from evaluation.public_catalog import PERSONAL, LINKAGE, protocol_hashes, score
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read, rows_for
from scripts.scan_data_asset import AssetScan, OPEN_MODEL, LOCAL_SERVER, write_report

ROOT = Path("data/open_validation")
# Source-derived annotations. No scanner outputs are used when assigning labels.
LABELS = {
    "flight_2": {
        "airlines": ("airline_directory", "uid:record_id:N Airline:organization_name:N Abbreviation:business_identifier:N Country:location:N"),
        "airports": ("airport_directory", "City:city:N AirportCode:record_id:N AirportName:airport_name:N Country:location:N CountryAbbrev:country_code:N"),
        "flights": ("flight_operations", "Airline:record_id:N FlightNo:record_id:N SourceAirport:reference_id:N DestAirport:reference_id:N"),
    },
    "network_1": {
        "Highschooler": ("student_directory", "ID:record_id:L name:person_name:D grade:grade_level:L"),
        "Friend": ("social_relationships", "student_id:reference_id:L friend_id:reference_id:L"),
        "Likes": ("social_relationships", "student_id:reference_id:L liked_id:reference_id:L"),
    },
    "student_transcripts_tracking": {
        "Addresses": ("address_directory", """address_id:record_id:U line_1:location:U line_2:location:U line_3:location:U
            city:city:U zip_postcode:postal_code:U state_province_county:location:U country:location:U other_address_details:free_text:U"""),
        "Courses": ("course_catalog", "course_id:record_id:N course_name:course_name:N course_description:free_text:N other_details:free_text:U"),
        "Departments": ("academic_structure", "department_id:record_id:N department_name:department:N department_description:free_text:N other_details:free_text:U"),
        "Degree_Programs": ("academic_structure", """degree_program_id:record_id:N department_id:reference_id:N
            degree_summary_name:degree_name:N degree_summary_description:free_text:N other_details:free_text:U"""),
        "Sections": ("course_catalog", "section_id:record_id:N course_id:reference_id:N section_name:section_name:N section_description:free_text:N other_details:free_text:U"),
        "Semesters": ("academic_calendar", "semester_id:record_id:N semester_name:academic_term:N semester_description:free_text:N other_details:free_text:U"),
        "Students": ("student_directory", """student_id:record_id:L current_address_id:reference_id:L permanent_address_id:reference_id:L
            first_name:person_name:D middle_name:person_name:D last_name:person_name:D cell_mobile_number:phone_number:D
            email_address:email_address:D ssn:ssn:D date_first_registered:date:L date_left:date:L other_student_details:free_text:U"""),
        "Student_Enrolment": ("enrollment", """student_enrolment_id:record_id:N degree_program_id:reference_id:N
            semester_id:reference_id:N student_id:reference_id:L other_details:free_text:U"""),
        "Student_Enrolment_Courses": ("enrollment", "student_course_id:record_id:N course_id:reference_id:N student_enrolment_id:reference_id:L"),
        "Transcripts": ("academic_records", "transcript_id:record_id:N transcript_date:date:L other_details:free_text:U"),
        "Transcript_Contents": ("academic_records", "student_course_id:reference_id:L transcript_id:reference_id:L"),
    },
    "world_1": {
        "city": ("cities", "ID:record_id:N Name:city:N CountryCode:reference_id:N District:location:N Population:count:N"),
        "country": ("countries", """Code:record_id:N Name:location:N Continent:location:N Region:location:N SurfaceArea:area:N
           IndepYear:year:N Population:count:N LifeExpectancy:life_expectancy:N GNP:financial_amount:N GNPOld:financial_amount:N
           LocalName:location:N GovernmentForm:category:N HeadOfState:person_name:D Capital:reference_id:N Code2:country_code:N"""),
        "countrylanguage": ("languages", "CountryCode:reference_id:N Language:record_id:N IsOfficial:boolean_flag:N Percentage:percentage:N"),
    },
}


def configuration(model, server):
    return {"commit": check_output(["git","rev-parse","HEAD"],text=True).strip(),
            "backend":fingerprint(Path(".")), "protocol":protocol_hashes(),
            "evaluator":digest(Path(__file__)), "gguf":digest(model), "server":digest(server),
            "runtime_dlls":{p.name:digest(p) for p in server.parent.glob("*.dll")},
            "model_name":model.name, "dictionary":None, "threads":4}


def freeze(root, model, server):
    seal=root/"seal.json"
    if seal.exists():
        raise FileExistsError(seal)
    inputs={}
    for name,tables in LABELS.items():
        db=root/(name+".sqlite")
        truth={}
        for table,(domain,spec) in tables.items():
            truth[table]={}
            for item in spec.split():
                col,typ,privacy=item.split(":")
                truth[table][col]={"semantic_type":typ,"domain":domain,"personal_data":PERSONAL[privacy],
                                   "personal_linkage":LINKAGE[privacy]}
        with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True) as conn:
            actual={t:{c[1] for c in conn.execute("PRAGMA table_info("+json.dumps(t)+")")}
                    for t, in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if actual!={t:set(cols) for t,cols in truth.items()}:
            raise ValueError(f"Unexpected label coverage for {name}")
        tags=root/(name+"_labels.json")
        write_report(tags,truth)
        inputs.update({x.name:digest(x) for x in (db,tags)})
    write_report(seal,{"configuration":configuration(model,server),"inputs":inputs})


def summarize(rows, entries, mode):
    m=score(rows,entries,mode)
    legacy=[r for r in rows if r["semantic_true"] not in TYPES]
    extended=[r for r in legacy if r["semantic_true"] in EXTENSIONS]
    novel=[r for r in legacy if r["semantic_true"] not in EXTENSIONS]
    for label,group in (("declared_extensions",extended),("open_types",novel)):
        m[label]={"fields":len(group),"exact_hits":sum(r["semantic_true"]==r["semantic_pred"] for r in group)}
    return m


def evaluate(root, model, server):
    seal=read(root/"seal.json")
    def verify():
        if (configuration(model,server)!=seal["configuration"]
                or any(digest(root/name)!=sha for name,sha in seal["inputs"].items())):
            raise ValueError("Frozen inputs or configuration changed.")
    verify()
    started=perf_counter()
    for mode in ("evidence","open"):
        folder=root/mode
        folder.mkdir(exist_ok=False)
        if mode=="evidence":
            scanner=AssetScan(mode)
            for name in LABELS:
                write_report(folder/(name+".json"),scanner.scan(root/(name+".sqlite")))
                print(mode,name,flush=True)
        else:
            with launch(server,model,threads=4) as runtime:
                scanner=AssetScan(mode,runtime=runtime)
                for name in LABELS:
                    report=scanner.scan(root/(name+".sqlite"))
                    write_report(folder/(name+".json"),report)
                    counts=Counter(r.get("context_status","absent") for r in report["classifications"])
                    print(mode,name,dict(counts),flush=True)
                write_report(folder/"runtime.json",{
                    **runtime.counters,"startup_seconds":runtime.startup_seconds,"peak_memory_mib":peak_memory(runtime.process.pid)})
    verify()
    result={}
    for mode in ("evidence","open"):
        all_rows,all_entries,sectors=[],[],{}
        for name in LABELS:
            truth=read(root/(name+"_labels.json"))
            report=read(root/mode/(name+".json"))
            predicts=report["classifications"]
            rows=rows_for(name,truth,predicts)
            entries=[(truth[r["table_name"]][r["column_name"]],r,{}) for r in predicts]
            all_rows.extend(rows)
            all_entries.extend(entries)
            sectors[name]={**summarize(rows,entries,mode),"scan_seconds":report["timing_seconds"]["total"],
                           "context_status":dict(Counter(r.get("context_status","absent") for r in predicts))}
        result[mode]={"overall":summarize(all_rows,all_entries,mode),"by_database":sectors}
    result["runtime"]=read(root/"open/runtime.json")
    result["wall_seconds"]=perf_counter()-started
    write_report(root/"metrics.json",result)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=("freeze","evaluate"))
    cli.add_argument("--model",type=Path,default=OPEN_MODEL)
    cli.add_argument("--server",type=Path,default=LOCAL_SERVER)
    args=cli.parse_args()
    {"freeze":freeze,"evaluate":evaluate}[args.action](ROOT,args.model,args.server)
