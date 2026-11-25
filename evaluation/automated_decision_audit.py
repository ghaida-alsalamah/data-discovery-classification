from pathlib import Path
from collections import Counter
from evaluation.score import read, rows_for
from evaluation.default_holdout import joint_by_membership
from scripts.scan_data_asset import write_report

root=Path("data/groq_anchor_holdout")
rows=[]
source={}
for p in sorted(root.glob("*_labels.json")):
 name=p.stem.removesuffix("_labels")
 predictions=read(root/"groq"/(name+".json"))["classifications"]
 rows.extend(rows_for(name,read(p),predictions))
 source.update({(name,r["table_name"],r["column_name"]):r for r in predictions})
def key(r):
 return r["sector"],r["table"],r["column"]
def rates(subset):
 return {"n":len(subset),"semantic":sum(r["semantic_true"]==r["semantic_pred"] for r in subset),
         "automatic":sum(not r["review_required"] for r in subset),
         "correct_auto":sum(not r["review_required"] and key(r) not in lookup for r in subset),
         "privacy_mismatches":sum(r["personal_true"] not in {"uncertain",r["personal_pred"]} for r in subset)}
all_auto=joint_by_membership([dict(r, review_required=False) for r in rows])
lookup={key(r):r for r in all_auto["errors"]}
bad=joint_by_membership(rows)["errors"]
groups={}
for r in rows:
 t,p=r["domain_true"],r["domain_pred"]
 counts=groups.setdefault(r["sector"],{})
 counts[t+" -> "+p]=counts.get(t+" -> "+p,0)+1
errors=[]
for r in bad:
 x=source[key(r)]
 dims=r["wrong_dimensions"]
 same_true=[a for a in rows if a["sector"]==r["sector"] and a["domain_true"]==r["domain_true"]]
 same_pred=[a for a in rows if a["sector"]==r["sector"] and a["domain_pred"]==r["domain_pred"]]
 domain_causes=[]
 if "group" in dims:
  if len({a["domain_true"] for a in same_pred})>1: domain_causes.append("merged distinct purposes")
  if len({a["domain_pred"] for a in same_true})>1: domain_causes.append("split expected purpose")
 privacy_cause = None
 if "privacy" in dims:
  if r["personal_true"] == "no" and x["privacy_role"] == "direct_identifier":
   privacy_cause = "identifier format accepted without correct contact ownership"
  elif r["personal_true"] == "yes" and x.get("context_privacy_hypothesis") != "linked":
   privacy_cause = "related attribute missed without corroborated field scope"
  else:
   privacy_cause = "related attribute not classified as personal despite contextual evidence"
 errors.append({**r,"privacy_cause":privacy_cause,"context_status":x["context_status"],"domain_resolution":x["domain_resolution"],
                "privacy_role":x["privacy_role"],"personal_linkage_evidence":x["personal_linkage_evidence"],
                "domain_causes":domain_causes})
bins={}
for lo,hi in [(0,.7),(.7,.85),(.85,.95),(.95,1.01)]:
 subset=[r for r in rows if r["confidence"] is not None and lo<=r["confidence"]<hi]
 bins[str(lo)+"-"+str(hi)]={**rates(subset),"joint":sum(key(r) not in lookup for r in subset)}
auc={}
for label, pred in [("semantic",lambda r:r["semantic_true"]==r["semantic_pred"]),
                    ("joint_all",lambda r:key(r) not in lookup),
                    ("joint_automatic",lambda r:key(r) not in lookup)]:
 rr=[r for r in rows if r["confidence"] is not None and (label!="joint_automatic" or not r["review_required"])]
 good=[r["confidence"] for r in rr if pred(r)]; poor=[r["confidence"] for r in rr if not pred(r)]
 auc[label]=sum((a>b)+.5*(a==b) for a in good for b in poor)/(len(good)*len(poor))
result={"dimensions":dict(Counter(d for r in errors for d in r["wrong_dimensions"])),
        "combinations":dict(Counter("+".join(r["wrong_dimensions"]) for r in errors)),
        "by_status":{status:rates([r for r in rows if source[key(r)]["context_status"]==status])
                     for status in sorted({x["context_status"] for x in source.values()})},
        "confidence_bins":bins,"confidence_auc":auc,"domain_memberships":groups,"errors":errors}
write_report(root/"automated_error_audit.json",result)
for k,v in result.items():
 if k!="errors": print(k,v)
for r in errors: print(r["sector"],r["table"],r["column"],r["wrong_dimensions"],r["domain_causes"],r["privacy_role"])

