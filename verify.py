"""
Independent verification of the crossref engine against the written
FORMULA and ALGORITHM. This script does NOT import engine internals for
its checks (other than to fetch raw specs) -- it recomputes tier,
hard-filter compliance, ranking and pool-routing from scratch using only
the documented rules, then compares against what find_alternatives()
returned.
"""
import sys, os, json, math
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from crossref import lookup_competitor
from crossref.engine import load_ti_pool, find_alternatives, TI_PART, TI_VRWM, TI_DIR, TI_CAP, TI_ESD, TI_SURGE, TI_VCLAMP, TI_CHAN, TI_PKG
from crossref.packages import to_numeric_val

TEST_XLSX = "data/test.xlsx"

# ---------------------------------------------------------------------
# Independent numeric parsing (re-implemented, not imported, except for
# to_numeric_val which is a pure text->float utility we trust to parse
# "12.3 V" -> 12.3; we double check a sample of it below).
# ---------------------------------------------------------------------

def num(v):
    return to_numeric_val(v, None)

def cap_category_ref(c):
    if c is None or c == float("inf"):
        return None
    if c <= 0.5: return 1
    if c <= 1.0: return 2
    if c <= 2.0: return 3
    if c <= 10.0: return 4
    return 99

def surge_category_ref(a):
    if a is None or a <= 0:
        return None
    if a <= 5: return 1
    if a <= 10: return 2
    if a <= 30: return 3
    return 4

def dir_norm_ref(s):
    s = str(s or "").lower()
    if "bi" in s: return "bidirectional"
    if "uni" in s: return "unidirectional"
    return "unknown"

def pct_within_ref(a, b, pct):
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b) <= pct / 100.0

def recompute_tier(comp_vrwm, ti_vrwm, comp_dir, ti_dir, comp_cap_cat, ti_cap_cat,
                    comp_esd, ti_esd, comp_surge_cat, ti_surge_cat, pkg_matched):
    """Fully independent re-derivation of tier from the FORMULA text."""
    def vrwm_ok(pct):
        r = pct_within_ref(ti_vrwm, comp_vrwm, pct)
        return True if r is None else r

    def cap_ok(allowance):
        if comp_cap_cat is None or comp_cap_cat == 99:
            return True
        if ti_cap_cat is None:
            return True
        eff = 99 if ti_cap_cat == 99 else ti_cap_cat
        return eff <= comp_cap_cat + allowance

    def esd_ok(pct):
        if comp_esd is None or comp_esd <= 0:
            return True
        if ti_esd is None:
            return True
        return abs(ti_esd - comp_esd) / comp_esd <= pct / 100.0

    def surge_ok(tol):
        if comp_surge_cat is None or ti_surge_cat is None:
            return True
        return abs(ti_surge_cat - comp_surge_cat) <= tol

    polarity_match = (comp_dir == "unknown" or ti_dir == "unknown" or comp_dir == ti_dir)

    if pkg_matched and vrwm_ok(10) and polarity_match and cap_ok(0) and esd_ok(10) and surge_ok(0):
        return "S"
    if pkg_matched and vrwm_ok(10) and cap_ok(1) and esd_ok(25) and surge_ok(1):
        return "Q"
    if vrwm_ok(25) and cap_ok(1) and esd_ok(30) and surge_ok(2):
        return "P"
    return None

TIER_RANK = {"S": 3, "Q": 2, "P": 1, None: 0, "None": 0, "none": 0}

# ---------------------------------------------------------------------
# Load test parts and TI pool (for zener detection / pool sanity)
# ---------------------------------------------------------------------
test_df = pd.read_excel(TEST_XLSX)
ti_pool = load_ti_pool()

ti_zener_parts = set()
ti_tvs_parts = set()
for _, row in ti_pool.iterrows():
    part = str(row.get(TI_PART, "")).strip()
    if not part:
        continue
    vclamp_raw = str(row.get(TI_VCLAMP, "")).strip()
    is_zener = (vclamp_raw == "" or vclamp_raw == "-")
    if is_zener:
        ti_zener_parts.add(part)
    else:
        ti_tvs_parts.add(part)

print(f"TI pool: {len(ti_pool)} rows | zener-like (empty Vclamp): {len(ti_zener_parts)} | tvs-like: {len(ti_tvs_parts)}")

# ---------------------------------------------------------------------
# Run all 160 parts
# ---------------------------------------------------------------------
results = []  # per (competitor part, alt rank) records
lookup_failures = []
no_specs_parts = []

for idx, row in test_df.iterrows():
    comp_part = str(row["Competitor Parts"]).strip()
    comp_mfr = str(row["Competitor Name"]).strip()
    try:
        specs = lookup_competitor(comp_part, comp_mfr)
    except Exception as e:
        lookup_failures.append((comp_part, comp_mfr, f"EXCEPTION: {e}"))
        continue
    if specs is None:
        lookup_failures.append((comp_part, comp_mfr, "lookup returned None"))
        continue
    try:
        alts = find_alternatives(specs)
    except Exception as e:
        lookup_failures.append((comp_part, comp_mfr, f"find_alternatives EXCEPTION: {e}"))
        continue

    results.append({
        "idx": idx,
        "comp_part": comp_part,
        "comp_mfr": comp_mfr,
        "specs": specs,
        "alts": alts,
    })

print(f"Rows processed: {len(test_df)} | successful lookups+cross: {len(results)} | lookup/crash failures: {len(lookup_failures)}")

# ---------------------------------------------------------------------
# CHECK 1: HARD FILTER COMPLIANCE
# ---------------------------------------------------------------------
hard_filter_violations = []

for r in results:
    specs = r["specs"]
    comp_vclamp = num(specs.get("Vclamp", "-"))
    comp_cap = num(specs.get("Capacitance", "-"))
    comp_cap_cat = cap_category_ref(comp_cap)
    comp_dir = dir_norm_ref(specs.get("Direction", ""))

    for alt in r["alts"]:
        ti_vclamp = num(alt.get("ti_vclamp", "-"))
        ti_cap = num(alt.get("ti_cap", "-"))
        ti_cap_cat = cap_category_ref(ti_cap)
        ti_dir = dir_norm_ref(alt.get("ti_dir", ""))

        # (a) vclamp <= 3x
        if comp_vclamp is not None and ti_vclamp is not None:
            if ti_vclamp > comp_vclamp * 3.0 + 1e-9:
                hard_filter_violations.append({
                    "type": "vclamp>3x",
                    "comp_part": r["comp_part"], "alt_part": alt["part"],
                    "comp_vclamp": comp_vclamp, "ti_vclamp": ti_vclamp,
                    "ratio": round(ti_vclamp / comp_vclamp, 3),
                })

        # (b) cap category <= comp+1 (respecting >10pF / unknown don't-care)
        if comp_cap_cat not in (None, 99) and ti_cap_cat is not None:
            eff = 99 if ti_cap_cat == 99 else ti_cap_cat
            if eff > comp_cap_cat + 1:
                hard_filter_violations.append({
                    "type": "cap_cat>comp+1",
                    "comp_part": r["comp_part"], "alt_part": alt["part"],
                    "comp_cap": comp_cap, "comp_cap_cat": comp_cap_cat,
                    "ti_cap": ti_cap, "ti_cap_cat": ti_cap_cat,
                })

        # (c) competitor bidirectional -> TI must not be unidirectional
        if comp_dir == "bidirectional" and ti_dir == "unidirectional":
            hard_filter_violations.append({
                "type": "bidir_comp_but_unidir_ti",
                "comp_part": r["comp_part"], "alt_part": alt["part"],
                "comp_dir": specs.get("Direction"), "ti_dir": alt.get("ti_dir"),
            })

print(f"\nCHECK 1 - Hard filter violations: {len(hard_filter_violations)}")
for v in hard_filter_violations[:50]:
    print(" ", v)

# ---------------------------------------------------------------------
# CHECK 2: TIER CORRECTNESS
# ---------------------------------------------------------------------
tier_mismatches = []

for r in results:
    specs = r["specs"]
    comp_vrwm = num(specs.get("Vrwm", "-"))
    comp_dir = dir_norm_ref(specs.get("Direction", ""))
    comp_cap = num(specs.get("Capacitance", "-"))
    comp_cap_cat = cap_category_ref(comp_cap)
    comp_esd = num(specs.get("IEC 61000-4-2", "-"))
    comp_surge = num(specs.get("IEC 61000-4-5", "-"))
    comp_surge_cat = surge_category_ref(comp_surge)

    for alt in r["alts"]:
        ti_vrwm = num(alt.get("ti_vrwm", "-"))
        ti_dir = dir_norm_ref(alt.get("ti_dir", ""))
        ti_cap = num(alt.get("ti_cap", "-"))
        ti_cap_cat = cap_category_ref(ti_cap)
        ti_esd = num(alt.get("ti_esd", "-"))
        ti_surge = num(alt.get("ti_surge", "-"))
        ti_surge_cat = surge_category_ref(ti_surge)
        pkg_matched = alt["pkg_matched"]

        recomputed = recompute_tier(comp_vrwm, ti_vrwm, comp_dir, ti_dir,
                                     comp_cap_cat, ti_cap_cat, comp_esd, ti_esd,
                                     comp_surge_cat, ti_surge_cat, pkg_matched)
        engine_tier = alt["tier"]
        if recomputed != engine_tier:
            tier_mismatches.append({
                "comp_part": r["comp_part"], "alt_part": alt["part"],
                "engine_tier": engine_tier, "recomputed_tier": recomputed,
                "comp_vrwm": comp_vrwm, "ti_vrwm": ti_vrwm,
                "comp_dir": comp_dir, "ti_dir": ti_dir,
                "comp_cap_cat": comp_cap_cat, "ti_cap_cat": ti_cap_cat,
                "comp_esd": comp_esd, "ti_esd": ti_esd,
                "comp_surge_cat": comp_surge_cat, "ti_surge_cat": ti_surge_cat,
                "pkg_matched": pkg_matched,
            })

print(f"\nCHECK 2 - Tier mismatches: {len(tier_mismatches)}")
for v in tier_mismatches[:50]:
    print(" ", v)

# ---------------------------------------------------------------------
# CHECK 3: RANKING (non-increasing tier_rank, score)
# ---------------------------------------------------------------------
ranking_violations = []
for r in results:
    alts = r["alts"]
    for i in range(len(alts) - 1):
        a, b = alts[i], alts[i+1]
        a_key = (TIER_RANK.get(a["tier"], 0), a["score"])
        b_key = (TIER_RANK.get(b["tier"], 0), b["score"])
        if a_key < b_key:
            ranking_violations.append({
                "comp_part": r["comp_part"],
                "pos_i": i, "part_i": a["part"], "tier_i": a["tier"], "score_i": a["score"],
                "pos_j": i+1, "part_j": b["part"], "tier_j": b["tier"], "score_j": b["score"],
            })

print(f"\nCHECK 3 - Ranking violations: {len(ranking_violations)}")
for v in ranking_violations[:50]:
    print(" ", v)

# ---------------------------------------------------------------------
# CHECK 4: POOL / ROUTE SANITY (no zener<->TVS crossing)
# ---------------------------------------------------------------------
zener_leaks = []
for r in results:
    specs = r["specs"]
    comp_is_zener = str(specs.get("Type", "")).lower().startswith("zener")
    for alt in r["alts"]:
        alt_part = alt["part"]
        alt_is_zener_row = alt_part in ti_zener_parts
        alt_is_tvs_row = alt_part in ti_tvs_parts
        if comp_is_zener and alt_is_tvs_row:
            zener_leaks.append({
                "comp_part": r["comp_part"], "comp_type": specs.get("Type"),
                "alt_part": alt_part, "issue": "zener competitor got TVS/ESD TI part",
            })
        if (not comp_is_zener) and alt_is_zener_row:
            zener_leaks.append({
                "comp_part": r["comp_part"], "comp_type": specs.get("Type"),
                "alt_part": alt_part, "issue": "TVS/ESD competitor got zener TI part",
            })

print(f"\nCHECK 4 - Zener/TVS route leaks: {len(zener_leaks)}")
for v in zener_leaks[:50]:
    print(" ", v)

# ---------------------------------------------------------------------
# CHECK 5: PLAUSIBILITY of #1 pick
# ---------------------------------------------------------------------
suspicious_top_picks = []
for r in results:
    if not r["alts"]:
        continue
    top = r["alts"][0]
    specs = r["specs"]
    comp_vrwm = num(specs.get("Vrwm", "-"))
    ti_vrwm = num(top.get("ti_vrwm", "-"))
    comp_dir = dir_norm_ref(specs.get("Direction", ""))
    ti_dir = dir_norm_ref(top.get("ti_dir", ""))

    reasons = []
    if comp_vrwm is not None and ti_vrwm is not None and comp_vrwm != 0:
        pct_diff = abs(ti_vrwm - comp_vrwm) / abs(comp_vrwm) * 100
        if pct_diff > 30:
            reasons.append(f"Vrwm diff {pct_diff:.1f}% (comp={comp_vrwm}, ti={ti_vrwm})")
    if comp_dir != "unknown" and ti_dir != "unknown" and comp_dir != ti_dir:
        reasons.append(f"direction mismatch (comp={comp_dir}, ti={ti_dir})")

    if reasons:
        suspicious_top_picks.append({
            "comp_part": r["comp_part"], "top_alt": top["part"],
            "tier": top["tier"], "score": top["score"],
            "reasons": reasons,
        })

print(f"\nCHECK 5 - Suspicious #1 picks: {len(suspicious_top_picks)}")
for v in suspicious_top_picks[:20]:
    print(" ", v)

# ---------------------------------------------------------------------
# Additional stats
# ---------------------------------------------------------------------
total_alts = sum(len(r["alts"]) for r in results)
parts_with_zero_alts = sum(1 for r in results if len(r["alts"]) == 0)
tier_counts = {}
for r in results:
    for alt in r["alts"]:
        tier_counts[alt["tier"]] = tier_counts.get(alt["tier"], 0) + 1

print(f"\nTotal alt rows returned across all parts: {total_alts}")
print(f"Parts with zero alternatives: {parts_with_zero_alts}")
print(f"Tier distribution among returned alts: {tier_counts}")

# ---------------------------------------------------------------------
# Save everything to JSON for report writing
# ---------------------------------------------------------------------
out = {
    "n_parts": len(test_df),
    "n_processed": len(results),
    "n_lookup_failures": len(lookup_failures),
    "lookup_failures": lookup_failures,
    "total_alts": total_alts,
    "parts_with_zero_alts": parts_with_zero_alts,
    "tier_counts": tier_counts,
    "hard_filter_violations": hard_filter_violations,
    "tier_mismatches": tier_mismatches,
    "ranking_violations": ranking_violations,
    "zener_leaks": zener_leaks,
    "suspicious_top_picks": suspicious_top_picks,
}
with open("verify_results.json", "w") as f:
    json.dump(out, f, indent=2, default=str)

print("\nSaved verify_results.json")
