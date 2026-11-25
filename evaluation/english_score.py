"""Score the frozen English fixture with the original strict and binary metrics."""
from pathlib import Path

from evaluation.reliability_infer import digest
from evaluation.reliability_score import measured
from evaluation.score import binary, read, rows_for
from evaluation.upstream_score import direct_report, direct_truth
from scripts.scan_data_asset import write_report


def score(root):
    if any(digest(root/name) != sha for name, sha in read(root/"manifest.json").items()):
        raise ValueError("The English fixture or its labels changed.")
    truth = read(root/"labels.json")
    results = {}
    for name, mode in (("before", "enhanced"), ("after", "english")):
        report = read(root/(name+".json"))
        if report["mode"] != mode:
            raise ValueError("Unexpected scanner mode.")
        rows = report["classifications"]
        base = measured(rows_for("english_business", truth, rows))
        entries = [(truth[r["table_name"]][r["column_name"]], r, {}) for r in rows]
        keys = ("fields", "strict_exact_accuracy", "broader_accuracy", "strict_domain_accuracy", "review_rate")
        results[name] = {
            **{k: base[k] for k in keys},
            "direct_pii": direct_report(entries, mode),
            "personal": base["personal"],
            "person_linked": binary([(direct_truth(label) == "linked", row["personal_linkage"] == "linked")
                                     for label, row, _ in entries if direct_truth(label) != "uncertain"]),
            "scan_seconds_excluding_initialization": report["timing_seconds"]["total"],
        }
    return results


if __name__ == "__main__":
    root = Path("data/english_acceptance")
    write_report(root/"metrics.json", score(root))
