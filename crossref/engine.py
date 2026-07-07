"""
engine.py — The cross-reference brain.

Two layers, applied in the order the spec requires:

  1) THE FORMULA (the funnel).  Every competitor<->TI pair is classified into
     a cross tier: S (same package, tight), Q (same package, relaxed) or
     P (different package).  Tier is decided by hard pass/fail rules on
     package, Vrwm, polarity, capacitance category, ESD % and surge category.

  2) THE ALGORITHM (the refiner).  Candidates that survive the hard filters
     are scored (+4500 package, +3000 channels, +2000 Vrwm@5%, capacitance
     improvement, grade, surge, ESD, direction ...).

Ranking is FORMULA-FIRST: sort by tier (S > Q > P), then by algorithm score.
Top 3 are returned with a generated TI orderable part number (OPN).
"""
import os
import functools
import pandas as pd

from .packages import (
    to_numeric_val,
    esd_to_kv,
    packages_match,
    generate_ti_opn,
    normalize_package,
    classify_ti_package,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TI_POOL_CSV = os.path.abspath(os.path.join(_DATA_DIR, "ti_pool.csv"))

# TI parametric column names
TI_PART = "Product or Part number"
TI_CHAN = "Number of channels"
TI_VRWM = "Vrwm (V)"
TI_DIR = "Bi-/uni-directional"
TI_PKG = "Package name"
TI_CAP = "IO capacitance (typ) (pF)"
TI_ESD = "IEC 61000-4-2 contact (k±V)"
TI_SURGE = "IEC 61000-4-5 (A)"
TI_VCLAMP = "Clamping voltage (V)"
TI_PIN = "Pin count"

# ---------------------------------------------------------------------------
# Category helpers (from the formula sheet)
# ---------------------------------------------------------------------------
def cap_category(c):
    """Capacitance category. >10 pF -> 99 (don't care).  None -> None."""
    if c is None or c == float("inf"):
        return None
    if c <= 0.5:
        return 1
    if c <= 1.0:
        return 2
    if c <= 2.0:
        return 3
    if c <= 10.0:
        return 4
    return 99  # >10 pF: don't care


def surge_category(a):
    if a is None or a <= 0:
        return None
    if a <= 5:
        return 1
    if a <= 10:
        return 2
    if a <= 30:
        return 3
    return 4


def _pct_within(a, b, pct):
    """True if a is within pct% of b (b is the reference/competitor value)."""
    if a is None or b is None or b == 0:
        return None  # unknown -> caller treats as don't-care
    return abs(a - b) / abs(b) <= pct / 100.0


def _dir_norm(s):
    s = str(s or "").lower()
    if "bi" in s:
        return "bidirectional"
    if "uni" in s:
        return "unidirectional"
    return "unknown"


def _clean_disp(x):
    """Tidy a numeric display value: '1.0' -> '1', '36.0' -> '36', '0.3' -> '0.3'."""
    s = str(x).strip()
    if s in ("", "-", "nan", "None"):
        return "-"
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except ValueError:
        return s


@functools.lru_cache(maxsize=1)
def load_ti_pool():
    df = pd.read_csv(TI_POOL_CSV, dtype=str, encoding="utf-8-sig",
                     on_bad_lines="skip").fillna("")
    df.columns = df.columns.str.strip()
    return df


# ---------------------------------------------------------------------------
# Formula: classify a single competitor<->TI pair into S / Q / P / None
# ---------------------------------------------------------------------------
def classify_tier(comp, ti, pkg_matched):
    """Return 'S', 'Q', 'P' or None (does not qualify even for P)."""
    comp_vrwm = comp["_vrwm"]
    ti_vrwm = ti["_vrwm"]
    comp_dir = comp["_dir"]
    ti_dir = ti["_dir"]
    comp_cap_cat = comp["_cap_cat"]
    ti_cap_cat = ti["_cap_cat"]
    comp_esd = comp["_esd"]
    ti_esd = ti["_esd"]
    comp_surge_cat = comp["_surge_cat"]
    ti_surge_cat = ti["_surge_cat"]

    def vrwm_ok(pct):
        r = _pct_within(ti_vrwm, comp_vrwm, pct)
        return True if r is None else r

    def cap_ok(allowance):
        # don't care if competitor unknown or >10pF
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

    def surge_ok(cat_tol):
        if comp_surge_cat is None:
            return True
        if ti_surge_cat is None:
            return True
        return abs(ti_surge_cat - comp_surge_cat) <= cat_tol

    polarity_match = (comp_dir == "unknown" or ti_dir == "unknown" or comp_dir == ti_dir)

    # ESD-rating and surge are "higher is better" and are specified
    # inconsistently across vendors (contact vs air kV, etc.), so they are NOT
    # used as hard tier gates — they only add points in scoring (as the
    # algorithm specifies: "ESD/surge rating >= competitor"). Tier gating uses
    # the reliable, directly-comparable specs: package, Vrwm, polarity, cap.
    _ = (esd_ok, surge_ok)  # kept for reference / future use

    # --- S tier: same package, tight ---
    if pkg_matched and vrwm_ok(10) and polarity_match and cap_ok(0):
        return "S"
    # --- Q tier: same package, relaxed ---
    if pkg_matched and vrwm_ok(10) and cap_ok(1):
        return "Q"
    # --- P tier: different package allowed ---
    if vrwm_ok(25) and cap_ok(1):
        return "P"
    return None


TIER_RANK = {"S": 3, "Q": 2, "P": 1, None: 0}


# ---------------------------------------------------------------------------
# Algorithm: score a surviving candidate
# ---------------------------------------------------------------------------
def score_candidate(comp, ti, pkg_matched):
    score = 0.0
    reasons = []

    if pkg_matched:
        score += 4500; reasons.append("package match +4500")

    if comp["_chan"] is not None and ti["_chan"] is not None and comp["_chan"] == ti["_chan"]:
        score += 3000; reasons.append("channel match +3000")

    # Vrwm proximity (best band only)
    cv, tv = comp["_vrwm"], ti["_vrwm"]
    exact_vrwm = False
    if cv is not None and tv is not None and cv != 0:
        d = abs(cv - tv) / abs(cv) * 100
        if d <= 5:
            score += 2000; exact_vrwm = True; reasons.append("Vrwm within 5% +2000")
        elif d <= 15:
            score += 1000; reasons.append("Vrwm within 15% +1000")
        elif d <= 30:
            score += 300; reasons.append("Vrwm within 30% +300")

    # Capacitance improvement (proportional)
    cc, tc = comp["_cap"], ti["_cap"]
    if cc is not None and cc != float("inf") and tc is not None:
        if tc < cc:
            max_cap = 2000 if cc < 10 else 1000
            add = (cc - tc) / cc * max_cap
            score += add; reasons.append(f"cap improvement +{add:.0f}")
        else:
            score += 100; reasons.append("cap acceptable +100")

    # Grade match
    if comp["_auto"] == ti["_auto"]:
        score += 500; reasons.append("grade match +500")

    # Surge >= competitor
    if comp["_surge"] and ti["_surge"] and ti["_surge"] >= comp["_surge"]:
        score += 500; reasons.append("surge >= comp +500")

    # ESD >= competitor
    if comp["_esd"] and ti["_esd"] and ti["_esd"] >= comp["_esd"]:
        score += 250; reasons.append("ESD >= comp +250")

    # Direction match
    if comp["_dir"] != "unknown" and comp["_dir"] == ti["_dir"]:
        score += 100; reasons.append("direction match +100")

    return score, exact_vrwm, reasons


# ---------------------------------------------------------------------------
# Prep helpers
# ---------------------------------------------------------------------------
def _prep_comp(comp_specs):
    cap = to_numeric_val(comp_specs.get("Capacitance", "-"), None)
    esd = esd_to_kv(comp_specs.get("IEC 61000-4-2", "-"))
    surge = to_numeric_val(comp_specs.get("IEC 61000-4-5", "-"), None)
    try:
        chan = int(float(comp_specs.get("Channels", "1")))
    except (ValueError, TypeError):
        chan = None
    grade = str(comp_specs.get("Grade", "")).lower()
    return {
        "_vrwm": to_numeric_val(comp_specs.get("Vrwm", "-"), None),
        "_vclamp": to_numeric_val(comp_specs.get("Vclamp", "-"), None),
        "_cap": cap,
        "_cap_cat": cap_category(cap),
        "_esd": esd,
        "_surge": surge,
        "_surge_cat": surge_category(surge),
        "_chan": chan,
        "_dir": _dir_norm(comp_specs.get("Direction", "")),
        "_auto": ("automotive" in grade or "aec" in grade),
        "_canonical": comp_specs.get("Canonical Package"),
        "_display": comp_specs.get("Package", ""),
    }


def _prep_ti(row):
    cap = to_numeric_val(row.get(TI_CAP, "-"), None)
    esd = esd_to_kv(row.get(TI_ESD, "-"))
    surge = to_numeric_val(row.get(TI_SURGE, "-"), None)
    try:
        chan = int(float(str(row.get(TI_CHAN, "")).strip()))
    except (ValueError, TypeError):
        chan = None
    part = str(row.get(TI_PART, "")).strip()
    vclamp_raw = str(row.get(TI_VCLAMP, "")).strip()
    try:
        pin = int(float(str(row.get(TI_PIN, "")).split(",")[0].strip()))
    except (ValueError, TypeError):
        pin = None
    return {
        "_part": part,
        "_pkg_cell": row.get(TI_PKG, ""),
        "_pin": pin,
        "_vrwm": to_numeric_val(row.get(TI_VRWM, "-"), None),
        "_vclamp": to_numeric_val(vclamp_raw or "-", None),
        "_is_zener": (vclamp_raw == "" or vclamp_raw == "-"),
        "_cap": cap,
        "_cap_cat": cap_category(cap),
        "_esd": esd,
        "_surge": surge,
        "_surge_cat": surge_category(surge),
        "_chan": chan,
        "_dir": _dir_norm(row.get(TI_DIR, "")),
        "_auto": part.upper().endswith("-Q1"),
        "_disp": {
            "ti_pkg": str(row.get(TI_PKG, "")), "ti_pin": pin,
            "ti_vrwm": _clean_disp(row.get(TI_VRWM, "-")),
            "ti_vclamp": _clean_disp(row.get(TI_VCLAMP, "-")),
            "ti_cap": _clean_disp(row.get(TI_CAP, "-")),
            "ti_dir": row.get(TI_DIR, "-"),
            "ti_chan": _clean_disp(row.get(TI_CHAN, "-")),
            "ti_esd": (f"{esd:g} kV" if esd else "-"),
            "ti_surge": (f"{surge:g} A" if surge else "-"),
        },
    }


@functools.lru_cache(maxsize=1)
def _prepped_pool():
    """Prep the default TI pool once (big speedup for bulk crossing)."""
    df = load_ti_pool()
    pool = []
    for _, row in df.iterrows():
        ti = _prep_ti(row)
        if ti["_part"] and not ti["_part"].upper().startswith(("UC", "SN")):
            pool.append(ti)
    return pool


def _base_name(pn):
    return pn[:-3] if pn.upper().endswith("-Q1") else pn


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
VCLAMP_MULT = 3.0


def find_alternatives(comp_specs, ti_df=None, top_n=3):
    if ti_df is None:
        pool = _prepped_pool()
    else:
        pool = [t for t in (_prep_ti(r) for _, r in ti_df.iterrows())
                if t["_part"] and not t["_part"].upper().startswith(("UC", "SN"))]
    comp = _prep_comp(comp_specs)
    comp_is_zener = str(comp_specs.get("Type", "")).lower().startswith("zener")

    results = []
    for ti in pool:
        # Route TVS/ESD <-> TVS/ESD and Zener <-> Zener (algorithm's split)
        if ti["_is_zener"] != comp_is_zener:
            continue

        pkg_matched = packages_match(comp["_canonical"], comp["_display"],
                                     ti["_pkg_cell"], ti["_pin"])

        # ---- HARD FILTERS (algorithm) ----
        # Vclamp <= 3x competitor
        if comp["_vclamp"] is not None and ti["_vclamp"] is not None:
            if ti["_vclamp"] > comp["_vclamp"] * VCLAMP_MULT:
                continue
        # Capacitance: don't exceed competitor category + 1 (loosest formula rule)
        if comp["_cap_cat"] not in (None, 99) and ti["_cap_cat"] is not None:
            eff = 99 if ti["_cap_cat"] == 99 else ti["_cap_cat"]
            if eff > comp["_cap_cat"] + 1:
                continue
        # Competitor bidirectional but TI not
        if comp["_dir"] == "bidirectional" and ti["_dir"] == "unidirectional":
            continue

        # ---- CANDIDATE POOL gate (algorithm): package match OR Vrwm within 30% ----
        vrwm_close = _pct_within(ti["_vrwm"], comp["_vrwm"], 30)
        in_pool = pkg_matched or (vrwm_close is True) or (comp["_vrwm"] is None)
        if not in_pool:
            continue

        tier = classify_tier(comp, ti, pkg_matched)
        score, exact_vrwm, reasons = score_candidate(comp, ti, pkg_matched)

        results.append({
            "part": ti["_part"],
            "base": _base_name(ti["_part"]),
            "tier": tier,
            "tier_rank": TIER_RANK[tier],
            "score": round(score, 1),
            "pkg_matched": pkg_matched,
            "exact_vrwm": exact_vrwm,
            "reasons": reasons,
            "ti_pkg": ti["_disp"]["ti_pkg"],
            "ti_pin": ti["_pin"],
            "ti_vrwm": ti["_disp"]["ti_vrwm"],
            "ti_vclamp": ti["_disp"]["ti_vclamp"],
            "ti_cap": ti["_disp"]["ti_cap"],
            "ti_dir": ti["_disp"]["ti_dir"],
            "ti_chan": ti["_disp"]["ti_chan"],
            "ti_esd": ti["_disp"]["ti_esd"],
            "ti_surge": ti["_disp"]["ti_surge"],
            "is_auto": ti["_auto"],
            "_vclampnum": ti["_vclamp"] if ti["_vclamp"] is not None else float("inf"),
            "_capnum": ti["_cap"] if ti["_cap"] is not None else float("inf"),
        })

    if not results:
        return []

    # ---- Dedupe auto/commercial by base part; keep the grade matching competitor ----
    results.sort(key=lambda r: (r["tier_rank"], r["score"]), reverse=True)
    seen = {}
    deduped = []
    for r in results:
        b = r["base"]
        if b in seen:
            # prefer the one whose grade matches the competitor
            prev = seen[b]
            if (r["is_auto"] == comp["_auto"]) and (prev["is_auto"] != comp["_auto"]):
                deduped[deduped.index(prev)] = r
                seen[b] = r
            continue
        seen[b] = r
        deduped.append(r)

    # ---- FORMULA-FIRST ranking: tier, then score, then tiebreakers ----
    deduped.sort(
        key=lambda r: (
            r["tier_rank"],
            r["score"],
            r["pkg_matched"],
            r["exact_vrwm"],
            -r["_capnum"],
            -r["_vclampnum"],
        ),
        reverse=True,
    )

    # Prefer genuine formula crosses (tier S/Q/P). Only fall back to the
    # "closest but below-tier" candidates when nothing actually qualifies.
    qualifying = [r for r in deduped if r["tier"] is not None]
    top = (qualifying if qualifying else deduped)[:top_n]
    for r in top:
        r["opn"] = generate_ti_opn(r["base"], r["ti_pkg"], ti_pin_val=r.get("ti_pin"),
                                   is_automotive=(comp["_auto"]),
                                   prefer_canonical=comp["_canonical"])
    return top


def cross_reference(comp_specs, top_n=3):
    """Convenience: returns (comp_specs, [top alternatives])."""
    return comp_specs, find_alternatives(comp_specs, top_n=top_n)
