"""
compare.py — Rich cross-reference output: for a competitor part, pick the best
TI cross(es), build a side-by-side spec-difference table, and classify the
replacement type (P2P / Drop-in / Functional / Different product line).
"""
import re
from .engine import find_alternatives, cap_category


def _n(x):
    """Bare leading number (no unit multipliers) — used to compare same-unit
    fields: clamp V vs clamp V, cap pF vs cap pF, ESD kV vs ESD kV."""
    if x is None:
        return None
    m = re.search(r"[-+]?\d*\.?\d+", str(x))
    return float(m.group(0)) if m else None


def replacement_type(alt):
    """P2P = same package. Drop-in = same package + tight match (tier S).
    Functional = different package but a valid electrical cross (tier P)."""
    if alt.get("pkg_matched"):
        return "Drop-in replacement" if alt.get("tier") == "S" else "P2P"
    if alt.get("tier") in ("P", "Q"):
        return "Functional"
    return "Functional (closest)"


# Spec rows: (label, comp_key, ti_key, direction) where direction says which way
# is "better" for TI:  'low' = lower is better, 'high' = higher is better,
# 'match' = matching the competitor is the goal, 'pkg' = same package = P2P.
_ROWS = [
    ("Channels", "Channels", "ti_chan", "match"),
    ("Direction", "Direction", "ti_dir", "match"),
    ("Working Voltage (Vrwm)", "Vrwm", "ti_vrwm", "vrwm"),
    ("Clamping Voltage", "Vclamp", "ti_vclamp", "low"),
    ("Capacitance (pF)", "Capacitance", "ti_cap", "low"),
    ("ESD IEC 61000-4-2 (kV)", "IEC 61000-4-2", "ti_esd", "high"),
    ("Surge IEC 61000-4-5 (A)", "IEC 61000-4-5", "ti_surge", "high"),
    ("Package", "Package", "ti_pkg", "pkg"),
]


def _fmt(v):
    s = "" if v is None else str(v).strip()
    return s if s and s not in ("-", "nan", "None") else "—"


def _dir_word(s):
    s = str(s or "").lower()
    if "bi" in s:
        return "Bidirectional"
    if "uni" in s:
        return "Unidirectional"
    return "—"


def spec_diff(comp_specs, alt):
    """Return rows [{label, comp, ti, verdict}] with verdict in
    better/equal/worse/na, plus a small tally."""
    rows = []
    for label, ck, tk, mode in _ROWS:
        comp_raw = comp_specs.get(ck, "")
        ti_raw = alt.get(tk, "")
        verdict = "na"

        if mode == "pkg":
            comp_v = _fmt(comp_raw)
            ti_v = _fmt(ti_raw)
            verdict = "better" if alt.get("pkg_matched") else "equal"  # same pkg highlighted
            if not alt.get("pkg_matched"):
                verdict = "na"
        elif mode == "match":
            if ck == "Direction":
                comp_v, ti_v = _dir_word(comp_raw), _dir_word(ti_raw)
            else:
                comp_v, ti_v = _fmt(comp_raw), _fmt(ti_raw)
            if comp_v != "—" and ti_v != "—":
                verdict = "equal" if comp_v.lower() == ti_v.lower() else "worse"
        else:
            comp_v, ti_v = _fmt(comp_raw), _fmt(ti_raw)
            cn, tn = _n(comp_raw), _n(ti_raw)
            if cn is None or tn is None:
                verdict = "na"
            elif mode == "low":
                verdict = "better" if tn < cn else ("equal" if abs(tn - cn) < 1e-9 else "worse")
            elif mode == "high":
                verdict = "better" if tn > cn else ("equal" if abs(tn - cn) < 1e-9 else "worse")
            elif mode == "vrwm":
                verdict = "equal" if abs(tn - cn) / cn <= 0.10 else "na"
        rows.append({"label": label, "comp": comp_v, "ti": ti_v, "verdict": verdict})
    return rows


def analyze(comp_specs, top_n=8):
    """Full analysis for one competitor part: best cross, a P2P option and a
    functional option, each with a spec-diff table and replacement type."""
    alts = find_alternatives(comp_specs, top_n=top_n)
    for a in alts:
        a["rtype"] = replacement_type(a)
        a["diff"] = spec_diff(comp_specs, a)

    best = alts[0] if alts else None
    p2p = next((a for a in alts if a.get("pkg_matched")), None)
    func = next((a for a in alts if not a.get("pkg_matched")), None)
    # columns for the side-by-side table: prefer showing a P2P and a functional
    cols = []
    for a in (p2p, func):
        if a and a not in cols:
            cols.append(a)
    if not cols and best:
        cols = [best]
    # if only one kind exists, add the next-best distinct alt
    if len(cols) == 1:
        for a in alts:
            if a not in cols:
                cols.append(a)
                break
    return {
        "specs": comp_specs,
        "best": best,
        "columns": cols[:2],
        "all": alts[:3],
        "found": bool(alts),
    }
