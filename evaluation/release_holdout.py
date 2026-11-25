"""Final validation of the offline default on seven separate public schemas."""
import argparse
from pathlib import Path
from subprocess import check_output
from time import perf_counter

from evaluation import default_holdout
from evaluation.public_catalog import protocol_hashes
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read, rows_for
from scripts.scan_data_asset import AssetScan, write_report

ROOT = Path("data/default_release_validation")
MODES = ("evidence", "default")

# Project annotations are based on schema, relationships and source field roles.
# Each field is included, even when the exact semantic type is outside the taxonomy.
LABELS = {
    "course_teach": {
        "course": ("course_catalog", "Course_ID:record_id:N Staring_Date:date:N Course:course_name:N"),
        "teacher": ("teacher_directory", "Teacher_ID:record_id:L Name:person_name:D Age:age:L Hometown:city:L"),
        "course_arrange": ("course_assignments", "Course_ID:reference_id:N Teacher_ID:reference_id:L Grade:academic_grade:L"),
    },
    "cre_Doc_Template_Mgt": {
        "Ref_Template_Types": ("template_library", "Template_Type_Code:record_id:N Template_Type_Description:free_text:N"),
        "Templates": ("template_library", """Template_ID:record_id:N Version_Number:code_version:N
            Template_Type_Code:reference_id:N Date_Effective_From:date:N Date_Effective_To:date:N Template_Details:free_text:N"""),
        "Documents": ("document_content", """Document_ID:record_id:N Template_ID:reference_id:N
            Document_Name:document_title:N Document_Description:free_text:N Other_Details:free_text:U"""),
        "Paragraphs": ("document_content", "Paragraph_ID:record_id:N Document_ID:reference_id:N Paragraph_Text:free_text:U Other_Details:free_text:U"),
    },
    "museum_visit": {
        "museum": ("museum_directory", "Museum_ID:record_id:N Name:museum_name:N Num_of_Staff:count:N Open_Year:year:N"),
        "visitor": ("visitor_directory", "ID:record_id:L Name:person_name:D Level_of_membership:category:L Age:age:L"),
        "visit": ("attendance", "Museum_ID:reference_id:N visitor_ID:reference_id:L Num_of_Ticket:count:L Total_spent:financial_amount:L"),
    },
    "poker_player": {
        "poker_player": ("competition_results", """Poker_Player_ID:record_id:N People_ID:reference_id:L
            Final_Table_Made:count:L Best_Finish:rank:L Money_Rank:rank:L Earnings:financial_amount:L"""),
        "people": ("player_directory", "People_ID:record_id:L Nationality:location:L Name:person_name:D Birth_Date:date:L Height:height:L"),
    },
    "real_estate_properties": {
        "Ref_Feature_Types": ("feature_catalog", "feature_type_code:record_id:N feature_type_name:category:N"),
        "Ref_Property_Types": ("property_catalog", "property_type_code:record_id:N property_type_description:category:N"),
        "Other_Available_Features": ("feature_catalog", """feature_id:record_id:N feature_type_code:reference_id:N
            feature_name:property_feature:N feature_description:free_text:N"""),
        "Properties": ("property_catalog", """property_id:record_id:N property_type_code:reference_id:N date_on_market:date:N
            date_sold:date:N property_name:property_name:N property_address:location:N room_count:count:N
            vendor_requested_price:price:N buyer_offered_price:price:N agreed_selling_price:price:N
            apt_feature_1:property_feature:N apt_feature_2:property_feature:N apt_feature_3:property_feature:N
            fld_feature_1:property_feature:N fld_feature_2:property_feature:N fld_feature_3:property_feature:N
            hse_feature_1:property_feature:N hse_feature_2:property_feature:N hse_feature_3:property_feature:N
            oth_feature_1:property_feature:N oth_feature_2:property_feature:N oth_feature_3:property_feature:N
            shp_feature_1:property_feature:N shp_feature_2:property_feature:N shp_feature_3:property_feature:N
            other_property_details:free_text:U"""),
        "Other_Property_Features": ("property_catalog", """property_id:reference_id:N feature_id:reference_id:N
            property_feature_description:free_text:N"""),
    },
    "singer": {
        "singer": ("performer_directory", """Singer_ID:record_id:L Name:person_name:D Birth_Year:year:L
            Net_Worth_Millions:financial_amount:L Citizenship:location:L"""),
        "song": ("music_catalog", "Song_ID:record_id:N Title:song_title:N Singer_ID:reference_id:L Sales:count:N Highest_Position:rank:N"),
    },
    "tvshow": {
        "TV_Channel": ("channel_directory", """id:record_id:N series_name:series_name:N Country:location:N Language:language:N
            Content:category:N Pixel_aspect_ratio_PAR:ratio:N Hight_definition_TV:boolean_flag:N
            Pay_per_view_PPV:boolean_flag:N Package_Option:category:N"""),
        "TV_series": ("television_audience", """id:record_id:N Episode:episode_title:N Air_Date:date:N Rating:rating:N
            Share:percentage:N 18_49_Rating_Share:rating_share:N Viewers_m:count:N Weekly_Rank:rank:N Channel:reference_id:N"""),
        "Cartoon": ("television_catalog", """id:record_id:N Title:episode_title:N Directed_by:person_name:D Written_by:person_name:D
            Original_air_date:date:N Production_code:business_identifier:N Channel:reference_id:N"""),
    },
}


def configuration(_model=None, _server=None):
    return {
        "commit": check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "backend": fingerprint(Path(".")), "protocol": protocol_hashes(),
        "evaluator": digest(Path(__file__)),
        "scoring": digest(Path(default_holdout.__file__)),
        "requirements": digest(Path("backend/requirements.txt")),
        "sources": {name: (ROOT / (name + ".source")).read_text(encoding="utf-8").strip() for name in LABELS},
        "dictionary": None, "modes": MODES,
        "group_membership_minimum": default_holdout.GROUP_MINIMUM,
    }


def evaluate():
    seal = read(ROOT / "seal.json")

    def verify():
        config = {**configuration(), "modes": list(MODES)}
        if (config != seal["configuration"]
                or any(digest(ROOT / name) != sha for name, sha in seal["inputs"].items())):
            raise ValueError("Frozen input, scanner or scorer changed.")

    verify()
    started = perf_counter()
    outputs = {}
    for mode in MODES:
        scanner = AssetScan(mode)
        folder = ROOT / mode
        folder.mkdir(exist_ok=False)
        outputs[mode] = {}
        for name in LABELS:
            report = scanner.scan(ROOT / (name + ".sqlite"))
            classifications = report["classifications"]
            artifact = {
                "schema": report["schema"], "classifications": classifications,
                "relationships": report["relationships"], "domains": report["domains"],
                "quality": report["quality"], "opportunities": report["opportunities"],
                "review_history": report["review_history"], "timing_seconds": report["timing_seconds"],
            }
            write_report(folder / (name + ".json"), artifact)
            outputs[mode][name] = artifact
            print(mode, name, len(classifications), flush=True)

    verify()
    result = {"configuration": seal["configuration"]}
    for mode, databases in outputs.items():
        pooled, pooled_entries, per_database = [], [], {}
        for name, report in databases.items():
            classifications = report["classifications"]
            truth = read(ROOT / (name + "_labels.json"))
            rows = rows_for(name, truth, classifications)
            by_key = {(r["table_name"], r["column_name"]): r for r in classifications}
            entries = [(truth[r["table"]][r["column"]], by_key[r["table"], r["column"]], {}) for r in rows]
            pooled.extend(rows)
            pooled_entries.extend(entries)
            per_database[name] = {
                **default_holdout.metrics(rows, entries, mode), "seconds": report["timing_seconds"]["total"],
            }
        result[mode] = {
            "overall": default_holdout.metrics(pooled, pooled_entries, mode),
            "by_database": per_database, "seconds": sum(db["seconds"] for db in per_database.values()),
        }
    result["wall_seconds"] = perf_counter() - started
    write_report(ROOT / "metrics.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "evaluate"))
    args = parser.parse_args()
    if args.action == "freeze":
        default_holdout.freeze(ROOT, None, None, labels=LABELS, configure=configuration)
    else:
        evaluate()
