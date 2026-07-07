"""
batch.py — Cross-reference a whole list of competitor parts.

Usage:
    python batch.py                      # runs the bundled data/test.xlsx
    python batch.py mylist.xlsx          # runs your own list
    python batch.py mylist.csv out.xlsx  # custom input + output

Input needs a competitor-part column and (optionally) a manufacturer column.
Writes an .xlsx with TI Alternate 1/2/3 plus a detailed audit sheet.
"""
import sys
import os
import pandas as pd

from crossref import lookup_competitor
from crossref.engine import find_alternatives


def run(in_path, out_path):
    df = pd.read_csv(in_path) if in_path.lower().endswith(".csv") else pd.read_excel(in_path)
    cn = next((c for c in df.columns if "part" in c.lower()), df.columns[0])
    mn = next((c for c in df.columns if "name" in c.lower() or "manufacturer" in c.lower()
               or "mfr" in c.lower()), None)

    simple, audit = [], []
    found = crossed = 0
    for _, r in df.iterrows():
        part = str(r[cn]).strip()
        if not part or part.lower() == "nan":
            continue
        mfr = str(r[mn]).strip() if mn else ""
        specs = lookup_competitor(part, mfr)
        if specs:
            found += 1
        alts = find_alternatives(specs) if specs else []
        if alts:
            crossed += 1
        names = [a["part"] for a in alts] + ["-"] * (3 - len(alts))
        simple.append([part, mfr, names[0], names[1], names[2]])
        audit.append({
            "Competitor Parts": part, "Competitor Name": mfr,
            "Matched": specs["Device Name"] if specs else "NOT FOUND",
            "Comp Pkg": specs["Package"] if specs else "-",
            "Comp Vrwm": specs["Vrwm"] if specs else "-",
            "Comp Vclamp": specs["Vclamp"] if specs else "-",
            "Comp Cap": specs["Capacitance"] if specs else "-",
            "Comp Dir": specs["Direction"] if specs else "-",
            "TI Alternate 1": names[0], "Tier 1": alts[0]["tier"] if len(alts) > 0 else "-",
            "Score 1": alts[0]["score"] if len(alts) > 0 else "-",
            "TI Alternate 2": names[1], "Tier 2": alts[1]["tier"] if len(alts) > 1 else "-",
            "TI Alternate 3": names[2], "Tier 3": alts[2]["tier"] if len(alts) > 2 else "-",
        })

    simple_df = pd.DataFrame(simple, columns=["Competitor Parts", "Competitor Name",
                             "TI Alternate 1", "TI Alternate 2", "TI Alternate 3"])
    audit_df = pd.DataFrame(audit)
    with pd.ExcelWriter(out_path) as xl:
        simple_df.to_excel(xl, index=False, sheet_name="Results")
        audit_df.to_excel(xl, index=False, sheet_name="Audit")
    total = len(simple)
    print(f"Done. {total} parts | found in master: {found} ({found/total:.0%}) | "
          f"produced a cross: {crossed} ({crossed/total:.0%})")
    print(f"Wrote {out_path}")
    return simple_df, audit_df


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    in_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "data", "test.xlsx")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "ti_cross_results.xlsx")
    run(in_path, out_path)
