"""
data_layer.py — Competitor part lookup against the 94k DigiKey master CSV.

IMPORTANT DATA-QUALITY NOTE: many rows in the master (Diodes Inc., Nexperia,
onsemi, STMicro, some Yageo/Bourns ...) are column-shifted in the later
parametric fields, so "Voltage - Clamping", "Voltage - Reverse Standoff",
"Package / Case", "Grade" etc. cannot be trusted positionally. The DigiKey
"Description" ("TVS DIODE 33VWM 53.3VC SMB") and "Detailed Description"
("53.3V Clamp 11.3A Ipp Tvs Diode Surface Mount DO-214AA (SMB)") fields ARE
consistently formatted and correctly positioned. We therefore parse Vrwm,
Vclamp, package and peak-pulse current from the TEXT first, and only fall
back to the parametric columns when the text lacks a value AND the row looks
aligned. Capacitance / bidirectional-channel columns sit before the shift and
are used when present; direction also falls back to the 'CA' naming
convention (…CA… = bidirectional).
"""
import os
import re
import functools
import pandas as pd

from .packages import classify_digikey_package, normalize_package

PART_COL = "Mfr Part #"
SUPPLIER_COL = "Manufacturer"

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MASTER_CSV = os.path.abspath(os.path.join(_DATA_DIR, "digikey_master.csv"))
_MASTER_PICKLE = os.path.abspath(os.path.join(_DATA_DIR, "_digikey_master_v2.pkl"))
SUPP_CSV = os.path.abspath(os.path.join(_DATA_DIR, "competitor_supplemental.csv"))


def _norm_key(s):
    return re.sub(r"[\W_]+", "", str(s).upper())


@functools.lru_cache(maxsize=1)
def load_supplemental():
    """Clean, direct-from-vendor competitor table (STMicro, Nexperia, Toshiba,
    Semtech, onsemi, Good-Ark). Searched before the DigiKey master because its
    spec columns are reliable. Built by build_supplemental.py."""
    if not os.path.exists(SUPP_CSV):
        return None
    df = pd.read_csv(SUPP_CSV, dtype=str).fillna("")
    df["_key"] = df["Part"].map(_norm_key)
    df["_mfr_l"] = df["Manufacturer"].astype(str).str.lower()
    df["_p5"] = df["_key"].str[:5]
    return df


def specs_from_supplemental(row):
    """Build the competitor spec dict from a clean supplemental row."""
    from .packages import classify_digikey_package
    pkg = str(row.get("Package", "")).strip()
    canon = classify_digikey_package(pkg, pkg) if pkg else None
    vr = str(row.get("Vrwm", "")).strip()
    vc = str(row.get("Vclamp", "")).strip()
    esd = str(row.get("IEC42_kV", "")).strip()
    surge = str(row.get("IEC45_A", "")).strip()
    ch = str(row.get("Channels", "")).strip()
    try:
        ch = str(int(float(ch))) if ch else "1"
    except (ValueError, TypeError):
        ch = "1"
    return {
        "Device Name": str(row.get("Part", "")).strip(),
        "Manufacturer": str(row.get("Manufacturer", "")).strip(),
        "Package": pkg or "-", "Canonical Package": canon,
        "Normalized Package": normalize_package(pkg),
        "Vrwm": f"{vr} V" if vr else "-",
        "Vclamp": f"{vc} V" if vc else "-",
        "Capacitance": str(row.get("Capacitance", "")).strip() or "-",
        "Channels": ch, "Direction": str(row.get("Direction", "")).strip() or "Unidirectional",
        "IEC 61000-4-2": f"{esd} kV" if esd else "-",
        "IEC 61000-4-5": f"{surge} A" if surge else "-",
        "Grade": str(row.get("Grade", "")).strip() or "Commercial",
        "Type": str(row.get("Type", "")).strip() or "TVS/ESD",
        "Source": "Vendor: " + str(row.get("Manufacturer", "")).strip(),
    }


@functools.lru_cache(maxsize=1)
def load_master():
    """Load the DigiKey master once (cached pickle with a precomputed key)."""
    if os.path.exists(_MASTER_PICKLE) and (
        not os.path.exists(MASTER_CSV)
        or os.path.getmtime(_MASTER_PICKLE) >= os.path.getmtime(MASTER_CSV)
    ):
        try:
            df = pd.read_pickle(_MASTER_PICKLE)
            if "_p5" not in df.columns:
                df["_p5"] = df["_key"].str[:5]
            return df
        except Exception:
            pass  # stale/incompatible cache — rebuild from CSV below
    df = pd.read_csv(MASTER_CSV, dtype=str, encoding="utf-8-sig",
                     on_bad_lines="skip", low_memory=False)
    df.columns = df.columns.str.strip()
    df = df.fillna("")
    df["_key"] = df[PART_COL].map(_norm_key)
    df["_mfr_l"] = df[SUPPLIER_COL].astype(str).str.lower()
    df["_p5"] = df["_key"].str[:5]
    try:
        df.to_pickle(_MASTER_PICKLE)
    except Exception:
        pass
    return df


# ---------------------------------------------------------------------------
# Part-number matching (exact -> substring -> longest-common-prefix)
# ---------------------------------------------------------------------------
def _lcp_len(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


# Max length of a trailing reel / packaging code that may differ between two
# orderable numbers for the SAME functional part (e.g. -7, -13-F, YL, ,115, -QR).
_MAX_REEL = 5


def _best_row(norm_input, search_df):
    """Return the best-matching row, or None. A match must agree with the input
    over almost its entire length — only a short trailing reel/packaging code may
    differ. This prevents false positives like PESD12VW1BCSF -> PESD12VSA where
    only a shared voltage prefix matches but the functional part differs."""
    keys = search_df["_key"]
    exact = search_df[keys == norm_input]
    if not exact.empty:
        return _prefer_active(exact)

    L = len(norm_input)
    if L < 6:
        return None
    sub = search_df[search_df["_p5"] == norm_input[:5]]
    if sub.empty:
        return None

    best_idx, best_score = None, -1
    for idx, k in sub["_key"].items():
        if not k:
            continue
        lcp = _lcp_len(k, norm_input)
        tail_in, tail_k = L - lcp, len(k) - lcp
        if lcp < 6:
            continue
        # Accept when it's a reel/packaging variant, i.e. EITHER one string is a
        # clean prefix of the other and only a packaging code is appended
        # (tail<=8), OR both differ by just a short reel code (tail<=3). Reject
        # divergent names that merely share a prefix (e.g. PESD12VW1BCSF vs
        # PESD12VSA: tails 6 and 2 -> different functional parts).
        clean_prefix = (tail_k == 0 and tail_in <= 8) or (tail_in == 0 and tail_k <= 8)
        # input almost fully explained by the match (only a short suffix differs),
        # catalog may add a slightly longer packaging code
        near = (tail_in <= 3 and tail_k <= 6)
        if clean_prefix or near:
            score = lcp * 10 - (tail_in + tail_k)
            if score > best_score:
                best_score, best_idx = score, idx
    if best_idx is None:
        return None
    # among equally-good matches, prefer an Active part
    winner_key = sub.loc[best_idx, "_key"]
    tied = sub[sub["_key"] == winner_key]
    return _prefer_active(tied) if len(tied) > 1 else sub.loc[best_idx]


def _prefer_active(frame):
    if "Product Status" in frame.columns:
        act = frame[frame["Product Status"].astype(str).str.contains("Active", case=False, na=False)]
        if not act.empty:
            return act.iloc[0]
    return frame.iloc[0]


# ---------------------------------------------------------------------------
# Text spec parsing from Description / Detailed Description
# ---------------------------------------------------------------------------
def _parse_text_specs(desc, detail):
    out = {"vrwm": None, "vclamp": None, "ipp": None, "pkg": "", "is_zener_txt": False}
    d = desc or ""
    dd = detail or ""

    m = re.search(r"([\d.]+)\s*VWM", d, re.I)
    if m:
        out["vrwm"] = m.group(1)

    # clamp from detailed "X V (Typ) Clamp"  (most reliable)
    m = re.search(r"([\d.]+)\s*V\s*(?:\([^)]*\)\s*)?Clamp", dd, re.I)
    if m:
        out["vclamp"] = m.group(1)
    else:  # clamp from description "…VWM 53.3VC …"  or "…VWM 14.5V …"
        m = re.search(r"VWM\s+([\d.]+)\s*V", d, re.I)
        if m:
            out["vclamp"] = m.group(1)

    m = re.search(r"Clamp\s+([\d.]+)\s*A", dd, re.I)
    if m:
        out["ipp"] = m.group(1)

    # package: text after "Surface Mount " in the detailed description
    m = re.search(r"Surface Mount\s+(.+)$", dd, re.I)
    if m:
        out["pkg"] = m.group(1).strip()
    if not out["pkg"]:
        # trailing token of the description after the clamp voltage
        m = re.search(r"V[C]?\s+([A-Za-z0-9][A-Za-z0-9\-()/. ]*)$", d)
        if m:
            out["pkg"] = m.group(1).strip()

    if re.search(r"\bZENER\b", d, re.I) and "TVS" not in d.upper():
        out["is_zener_txt"] = True
    return out


def _looks_voltage(x):
    return bool(re.match(r"^\s*[\d.]+\s*V", str(x)))


def _clean_num_unit(val):
    if val is None:
        return "-"
    s = str(val).strip()
    if s == "" or s == "-":
        return "-"
    m = re.match(r"^\s*([±]?\s*[-+]?[\d.]+)\s*([a-zA-ZµΩμ%]+)?", s)
    if not m:
        return s
    number = m.group(1).replace(" ", "")
    unit = m.group(2) or ""
    return f"{number} {unit}".strip() if unit else number


def lookup_competitor(part_input, manufacturer="", df=None):
    norm_input = _norm_key(part_input)
    if not norm_input:
        return None
    mfr = str(manufacturer or "").strip().lower()

    # 1) DigiKey 94k master first — it has per-orderable package granularity
    #    (e.g. the SOT-23 vs DFN variant of the same base part).
    if df is None:
        df = load_master()
    if df is not None and not df.empty:
        search_df = df
        if mfr:
            sub = df[df["_mfr_l"].str.contains(re.escape(mfr), na=False)]
            if not sub.empty:
                search_df = sub
        row = _best_row(norm_input, search_df)
        if row is None and search_df is not df:
            row = _best_row(norm_input, df)
        if row is not None:
            return specs_from_row(row)

    # 2) Vendor supplemental table — fills gaps for parts absent from the master
    #    (clean, direct-from-manufacturer specs).
    sup = load_supplemental()
    if sup is not None and not sup.empty:
        sdf = sup
        if mfr:
            f = sup[sup["_mfr_l"].str.contains(re.escape(mfr), na=False)]
            if not f.empty:
                sdf = f
        srow = _best_row(norm_input, sdf)
        if srow is None and sdf is not sup:
            srow = _best_row(norm_input, sup)
        if srow is not None:
            return specs_from_supplemental(srow)
    return None


def parse_name_hints(part):
    """Best-effort spec hints parsed from a competitor part NAME, used to
    pre-fill the manual 'cross by specs' form when the part isn't in the DB.
    Heuristic only — never used for automatic crossing."""
    p = str(part).upper()
    hints = {"vrwm": "", "direction": "Unidirectional", "grade": "Commercial"}
    # working voltage
    m = (re.search(r"PESD(\d+)V(\d)?", p) or re.search(r"(?:SM[ABC]J|TPSMB|P6SM[ABC]J|SMF\d*L?)(\d+)", p)
         or re.search(r"(\d+)V(\d)?", p))
    if m:
        v = m.group(1)
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            v = f"{v}.{m.group(2)}"
        hints["vrwm"] = v
    # directionality markers: 'CA'/'CB' or a 'B' polarity flag or CAN/RS485 bus
    if re.search(r"C[AB]Q?\d*(?:[-/]|$)", p) or re.search(r"\dB[A-Z]*$", p) or "CAN" in p or "RS485" in p:
        hints["direction"] = "Bidirectional"
    if re.search(r"AEC|[-/]Q\b|Q1\b", p) or p.endswith("-Q"):
        hints["grade"] = "Automotive"
    return hints


def build_manual_specs(vrwm="", package="", capacitance="", direction="Unidirectional",
                       channels="1", grade="Commercial", vclamp="", name="(manual entry)"):
    """Build a competitor spec dict from user-supplied fields, so ANY part
    (even one absent from the master) can be crossed with the same engine."""
    from .packages import classify_digikey_package
    pkg = str(package).strip()
    canon = classify_digikey_package(pkg, pkg) if pkg else None

    def _v(x):
        x = str(x).strip()
        return "-" if x == "" else (x if re.search(r"[a-zA-Z]", x) else f"{x} V")
    return {
        "Device Name": name, "Manufacturer": "", "Package": pkg or "-",
        "Canonical Package": canon, "Normalized Package": normalize_package(pkg),
        "Vrwm": _v(vrwm), "Vclamp": _v(vclamp),
        "Capacitance": str(capacitance).strip() or "-",
        "Channels": str(channels).strip() or "1",
        "Direction": direction or "Unidirectional",
        "IEC 61000-4-5": "-", "IEC 61000-4-2": "-",
        "Grade": grade or "Commercial", "Type": "TVS/ESD", "Source": "manual specs",
    }


def specs_from_row(row):
    """Build the normalized competitor spec dict directly from a master row.
    Used both by lookup_competitor and by bulk precomputation."""
    def g(col):
        v = str(row.get(col, "-")).strip() if col in row.index else "-"
        return "-" if v.lower() in ("", "nan", "none") else v

    desc = g("Description")
    detail = g("Detailed Description")
    txt = _parse_text_specs(desc if desc != "-" else "", detail if detail != "-" else "")

    # ---- Vrwm / Vclamp : text first, parametric fallback only if aligned ----
    col_vrwm = g("Voltage - Reverse Standoff (Typ)")
    col_vclamp = g("Voltage - Clamping (Max) @ Ipp")
    aligned = _looks_voltage(col_vrwm) and _looks_voltage(col_vclamp)
    vrwm = txt["vrwm"] or (col_vrwm if aligned and _looks_voltage(col_vrwm) else "-")
    vclamp = txt["vclamp"] or (col_vclamp if aligned and _looks_voltage(col_vclamp) else "-")
    vrwm = f"{vrwm} V" if vrwm not in ("-", None) and not str(vrwm).lower().endswith("v") else (vrwm or "-")
    vclamp = f"{vclamp} V" if vclamp not in ("-", None) and not str(vclamp).lower().endswith("v") else (vclamp or "-")

    # ---- Package : text descriptor first (has dims + pins), parametric backup ----
    supplier_device_pkg = g("Supplier Device Package")
    case_pkg = g("Package / Case")
    text_pkg = txt["pkg"]
    # choose a package source that isn't a shifted temperature/garbage value
    def _is_garbage_pkg(x):
        return ("°C" in x) or (x in ("-", "")) or bool(re.match(r"^\d+$", x))
    sup_for_class = text_pkg if text_pkg else (supplier_device_pkg if not _is_garbage_pkg(supplier_device_pkg) else "")
    case_for_class = supplier_device_pkg if not _is_garbage_pkg(supplier_device_pkg) else (
        case_pkg if not _is_garbage_pkg(case_pkg) else "")
    canonical = classify_digikey_package(sup_for_class, case_for_class)
    display_pkg = text_pkg or (supplier_device_pkg if not _is_garbage_pkg(supplier_device_pkg) else case_pkg)

    # ---- Capacitance (column sits before the shift; trust when present) ----
    cap = g("Capacitance @ Frequency")
    cap = cap if (cap != "-" and re.search(r"[\d.]", cap)) else "-"

    # ---- Direction / channels ----
    # 'Applications' + part name sit BEFORE the shift, so they're reliable even
    # when the Bi-/Unidirectional-Channels columns are blank on shifted rows.
    uni = g("Unidirectional Channels")
    bi = g("Bidirectional Channels")
    pn_up = g(PART_COL).upper()
    apps = g("Applications")
    blob = f"{pn_up} {apps.upper()} {(desc if desc != '-' else '').upper()}"
    # differential-bus protection is inherently bidirectional (both signal lines)
    _DIFF_BUS = ("CANFD", "CAN-FD", "CAN", "RS485", "RS-485", "RS232", "RS-232",
                 "FLEXRAY", "PROFIBUS", "ETHERNET")
    is_diffbus = any(k in blob for k in _DIFF_BUS)

    if bi not in ("-", "0") and bi.isdigit():
        direction, channels = "Bidirectional", bi
    elif uni not in ("-", "0") and uni.isdigit():
        direction, channels = "Unidirectional", uni
    else:
        # 'CA'/'CB' suffix (optionally + AEC 'Q' grade / reel code) = bidirectional
        # TVS, e.g. SMBJ36CA-7, SMF4L17CAQ-7, SMAJ13CAQ-13-F, P4SMAJ15CA.
        ca_bi = bool(re.search(r"C[AB]Q?\d*(?:[-/]|$)", pn_up))
        direction = "Bidirectional" if (ca_bi or is_diffbus) else "Unidirectional"
        m = re.search(r"(\d+)\s*CAN", blob) or re.search(r"(\d+)\s*RS-?485", blob)
        if m:
            channels = m.group(1)          # e.g. PESD2CANFD -> 2 channels
        elif is_diffbus:
            channels = "2"
        else:
            channels = "1"

    # ---- Type ----
    dk_type = g("Type").lower()
    is_zener = (vclamp == "-") and (txt["is_zener_txt"] or "zener" in dk_type)

    # ---- Grade / automotive ----
    # The 'Grade' column is frequently shifted, so scan the WHOLE row for the
    # AEC-Q / automotive flag (it commonly lands in Supplier Device Package).
    row_blob = " ".join(str(v) for v in row.values).upper()
    is_auto = ("AEC" in row_blob or "AUTOMOTIVE" in row_blob
               or bool(re.search(r"(?:^|[-/])Q1?(?:[-/]|$)", pn_up)))
    grade = "Automotive" if is_auto else "Commercial"

    return {
        "Device Name": g(PART_COL),
        "Manufacturer": g(SUPPLIER_COL),
        "Package": display_pkg,
        "Canonical Package": canonical,
        "Normalized Package": normalize_package(display_pkg),
        "Vrwm": vrwm,
        "Vclamp": vclamp,
        "Ipp": (f"{txt['ipp']} A" if txt["ipp"] else "-"),
        "Capacitance": _clean_num_unit(cap),
        "Channels": channels,
        "Direction": direction,
        "IEC 61000-4-5": "-",   # not present in the master
        "IEC 61000-4-2": "-",
        "Grade": grade,
        "Type": "Zener" if is_zener else "TVS/ESD",
        "Datasheet": g("Datasheet"),
        "Product URL": g("Product URL"),
        "Source": "DigiKey master",
    }
