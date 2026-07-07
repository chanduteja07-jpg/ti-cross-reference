"""
packages.py — Package normalization: the common base between competitor
(DigiKey) package strings and TI package names.

Every package this tool understands maps to a *canonical code* like
"SOT233_3", "DFN1006_2", "SC703_3". Competitor strings (from the DigiKey
master) and TI strings (from the TI parametric file) are both reduced to
this same code space, so matching is package-convention agnostic:
dashes, commas, spaces, JEDEC vs. metric names, and pin-count suffixes are
all normalized away.

This is the accuracy-critical module. Domain rules are carried over from the
production crossing code and consolidated here.
"""
import re

# ---------------------------------------------------------------------------
# Numeric parsing (voltages, capacitance, current) -> base units
# ---------------------------------------------------------------------------
def to_numeric_val(value_str, default_if_error=float("inf")):
    """Extract a numeric value, honoring k/m/µ prefixes.
    Base units: V for voltage, pF for capacitance, nA for current."""
    if value_str is None or value_str == "-":
        return default_if_error
    s = str(value_str).lower()
    m = re.search(r"([-+]?[\d.]+)", s)
    if not m:
        return default_if_error
    try:
        val = float(m.group(1))
    except ValueError:
        return default_if_error
    if "kv" in s:
        val *= 1000
    elif "mv" in s:
        val /= 1000
    elif "nf" in s:
        val *= 1000
    elif "uf" in s or "µf" in s or "μf" in s:
        val *= 1_000_000
    elif "µa" in s or "ua" in s or "μa" in s:
        val *= 1000
    elif "ma" in s:
        val *= 1_000_000
    return val


def is_number(x):
    return x is not None and x != float("inf") and x == x  # not inf, not NaN


def esd_to_kv(x):
    """Normalize an IEC 61000-4-2 ESD rating to kV. Some sources store it in
    volts (e.g. 30000 = 30 kV), others in kV (30). Returns a float or None."""
    v = to_numeric_val(x, None)
    if v is None or v == float("inf"):
        return None
    return v / 1000.0 if v > 100 else v


# ---------------------------------------------------------------------------
# String-level package normalization (display + coarse matching)
# ---------------------------------------------------------------------------
def normalize_package(pkg_str_input):
    """Reduce a single package token to a canonical uppercase string with
    dashes/spaces removed and common JEDEC/metric aliases unified.
    ALWAYS returns a string (possibly '')."""
    if pkg_str_input is None:
        return ""
    s = str(pkg_str_input).strip()
    if s == "" or s == "-":
        return ""
    norm = s.upper()
    norm = re.sub(r"\s+THIN\b", "", norm).strip()
    original = norm
    # strip parenthetical annotations like "(SMB)" or "(1005 Metric)"
    norm = re.sub(r"\s*\([A-Z0-9\-\s/.]+\)", "", norm).strip()
    flat = norm.replace("-", "").replace(" ", "")

    # SOT-23 family
    if norm == "SOT-23-6" or flat in ("SOT26", "TSOT26", "6TSOP", "SOT236"):
        return "SOT236"
    if norm == "SOT-23-5" or flat in ("SOT25", "SOT235") or "DBV" in original:
        return "SOT235"
    if norm == "SOT-23-4" or flat in ("SOT234", "SOT143", "SC594"):
        return "SOT234"
    if norm in ("SOT-23-3", "SOT-23") or flat in ("SOT233", "TO2363", "SC59", "TO236AB", "SOT23"):
        return "SOT233"
    # SC70 / SOT-363 / SOT-323
    if norm == "SC70-6" or flat in ("6TSSOP", "SC88", "SOT363", "SC706"):
        return "SC706"
    if norm == "SC70-3" or flat in ("SC703", "SOT323"):
        return "SC703"
    # SOT-5X3 / 6X3 family
    if flat in ("SOT563", "SOT5X3", "SOT553"):
        return "SOT563"
    if flat in ("SOT666", "SOT663"):
        return "SOT666"
    if flat in ("SOT523",):
        return "SOT523"
    # metric DFN / SON  (per TI package reference: X1SON=DFN1006, X2SON=DFN0603,
    # SOD-882/0402=DFN1006, SOD-962/0603=DFN0603)
    if ("0402" in norm or "1006" in norm or "X1SON" in norm or "2-XDFN" in norm
            or "DFN1006" in flat or "SOD882" in flat):
        return "DFN1006"
    if ("0201" in norm or "0603" in norm or "DFN0603" in flat or "X2SON" in norm
            or "SOD962" in flat or flat == "SL2"):   # SL2 = Toshiba SOD-962 = DFN0603
        return "DFN0603"
    if "DFN2510" in flat or "10-UFDFN" in norm or "10UFDFN" in flat or "UFDFN-10" in norm:
        return "DFN2510"
    # JEDEC surface-mount TVS bodies (DO-214 family etc.)
    if "DO214AB" in flat:
        return "SMC"
    if "DO214AA" in flat:
        return "SMB"
    if "DO214AC" in flat:
        return "SMA"
    if "DO219AB" in flat or flat == "SOD128":
        return "SOD128"
    if "DO219AA" in flat or flat == "SOD123":
        return "SOD123"
    if flat in ("DO221AC", "SMF", "SOD123FL", "SOD123F"):
        return "SOD123F"

    cleaned = re.sub(r"[\s-]+", "", norm)
    return cleaned if cleaned else re.sub(r"[\s-]+", "", original)


# ---------------------------------------------------------------------------
# Pin-marker / dimension helpers for the DigiKey classifier
# ---------------------------------------------------------------------------
def _flat(t):
    return str(t or "").upper().replace(" ", "")


def _has_pin_marker(text, pin_n):
    t = _flat(text)
    pats = [rf"-{pin_n}L?\b", rf"\b{pin_n}-(?:PIN|LEAD|SON|SOT|TSSOP|VSSOP|UQFN|WQFN|WSON|UFDFN|XFDFN|DFN|TSOP)",
            rf"\({pin_n}\)"]
    return any(re.search(p, t) for p in pats)


def _has_pin_count_anywhere(text, pin_n):
    return bool(re.search(rf"(^|[^0-9]){pin_n}([^0-9]|$)", _flat(text)))


def _has_dim(text, *variants):
    t = str(text or "").upper().replace(" ", "")
    return any(v.upper().replace(" ", "") in t for v in variants)


# ---------------------------------------------------------------------------
# Canonical classifiers  (competitor/DigiKey  and  TI)
# ---------------------------------------------------------------------------
def classify_digikey_package(supplier_pkg, case_pkg):
    """Canonical code for a DigiKey part from Supplier Device Package (primary)
    and Package / Case (backup, for pin info). None if no rule matches."""
    sup = str(supplier_pkg or "").strip().upper()
    case = str(case_pkg or "").strip().upper()
    combined = f"{sup} {case}"
    if not sup and not case:
        return None

    if _has_dim(combined, "SOD523", "SOD-523"):
        return "SOD523_2"
    if _has_dim(combined, "SOD323", "SOD-323"):
        return "SOD323_2"

    is_0603_dim = _has_dim(sup, "0.6x0.3", ".6x0.3", "0.6x.3", "0.62x0.32")
    is_0603_token = bool(re.search(r"(^|[^0-9])0603([^0-9]|$)", sup))
    is_0808_dim = _has_dim(sup, "0.8x0.8", "0808")
    if is_0808_dim and _has_pin_marker(combined, 4):
        return "X2SON_4"
    if "X2SON" in sup:
        return "X2SON_4"
    if (is_0603_dim or is_0603_token) and not _has_dim(sup, "0201"):
        if _has_pin_marker(case, 3) or _has_pin_count_anywhere(case, 3):
            return None
        return "DFN0603_2"
    if _has_dim(sup, "0201"):
        if _has_pin_marker(case, 3) or _has_pin_count_anywhere(case, 3):
            return None
        return "DFN0603_2"
    # DFN1006 == 1.0x0.6 mm body. SOD-882 and imperial 0402 are the same body.
    if _has_dim(sup, "1x0.6", "1.0x0.6", "1006", "0402", "SOD882", "SOD-882"):
        return "DFN1006_3" if _has_pin_marker(combined, 3) else "DFN1006_2"
    if _has_dim(sup, "1.6x1.6", "1616") and _has_pin_marker(combined, 6):
        return "DFN1616_6"
    if _has_dim(sup, "1110", "1.1x1.0", "1.1x1"):
        return "DFN1110_3"
    if _has_dim(sup, "2x2", "2020"):
        return "DFN2020_6"
    if _has_dim(sup, "2510", "2.5x1.0", "2.5x1"):
        return "DFN2510_10"
    if _has_dim(sup, "1.45x1.0", "1.45x1", "886") and _has_pin_marker(combined, 6):
        return "SOT886_6"
    if "SOT886" in sup.replace("-", "") or "SOT-886" in sup:
        return "SOT886_6"
    if "XSON" in sup and _has_pin_marker(combined, 6):
        return "SOT886_6"
    if _has_dim(sup, "1.6x1.6") and _has_pin_marker(combined, 6) and "USON" in combined:
        return "USON_6"
    if _has_dim(sup, "3x3", "3030") or "MSOP" in sup:
        return "DFN3030_8"
    if "DSBGA" in sup:
        return "DSBGA_4"
    m_sc = re.search(r"SC-?70-?([45])", sup)
    if m_sc:  # rare 4/5-pin SC70 — keep distinct from the 3-pin body
        return f"SC70{m_sc.group(1)}_{m_sc.group(1)}"
    if re.search(r"SC-?70-?3", sup) or "SOT323" in sup.replace("-", "") or (
        re.search(r"SC-?70", sup) and not re.search(r"SC-?70-?6", sup) and "SC88" not in sup.replace("-", "")):
        return "SC703_3"
    if re.search(r"SC-?70-?6", sup) or "SOT363" in sup.replace("-", "") or "SC88" in sup.replace("-", "").replace(" ", ""):
        return "SC706_6"
    _sfx = sup.replace("-", "").replace(" ", "")
    if "SOT23" in _sfx or "SOT143" in _sfx or "TO236" in _sfx:
        sup_clean = _sfx
        if "SOT143" in sup_clean:
            return "SOT234_4"
        if _has_pin_marker(combined, 5):
            return "SOT235_5"
        if _has_pin_marker(combined, 6):
            return "SOT236_6"
        if _has_pin_marker(combined, 4):
            return "SOT234_4"
        return "SOT233_3"
    if "SOT523" in sup.replace("-", "").replace(" ", ""):
        return "SOT523_2"
    if "SOT553" in sup.replace("-", "").replace(" ", ""):
        return "SOT553_5"
    if _has_dim(sup, "1x1") and _has_pin_marker(combined, 3):
        return "SOT9X3_3"
    if "UQFN" in sup or "U-QFN" in sup:
        if _has_dim(sup, "3.5x1.35", "3.5x1.4"):
            return "UQFN_14"
        if _has_dim(sup, "2.0x1.5", "2x1.5"):
            return "UQFN_10"
        if "10-UQFN" in case.replace(" ", "") or _has_pin_marker(combined, 10):
            return "UQFN_10"
        if _has_pin_marker(combined, 14):
            return "UQFN_14"
    if "WQFN" in sup:
        if _has_dim(sup, "4x4") or _has_pin_marker(combined, 12):
            return "WQFN_12"
    if "WSON" in sup:
        if _has_dim(sup, "3x3") and _has_pin_marker(combined, 6):
            return "WSON_6"
        if _has_pin_marker(combined, 15) or "15-SON" in case.replace(" ", ""):
            return "WSON_15"
        if _has_pin_marker(combined, 6):
            return "WSON_6"
    if "15-SON" in sup.replace(" ", "") or "15SON" in sup.replace(" ", "").replace("-", ""):
        return "WSON_15"

    # Final fallback: run both the supplier and case strings through the string
    # normalizer and accept any recognized 2-lead body (catches SL2, JEDEC
    # bodies, and '0201 (0603 Metric)' style case values).
    for cand in (sup, case):
        nb = normalize_package(cand)
        if nb in ("DFN0603", "DFN1006", "SMA", "SMB", "SMC",
                  "SOD123", "SOD128", "SOD123F", "SOD323", "SOD523"):
            return f"{nb}_2"
    return None


def _infer_pins_from_ti_pkg(ti_pkg_token, pin_val=None):
    """Best-effort pin count for a TI package token when Pin count col absent."""
    if pin_val:
        try:
            return int(float(pin_val))
        except (ValueError, TypeError):
            pass
    t = str(ti_pkg_token or "").upper()
    m = re.search(r"SOT-?23-?(\d)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"SC-?70-?(\d)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"DFN\d{4}-?(\d)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"-(\d+)\b", t)
    if m:
        return int(m.group(1))
    defaults = {"SOT-23": 3, "SC70-3": 3, "SC70-6": 6, "SOD323": 2, "SOD523": 2,
                "DFN1006": 2, "DFN0603": 2, "DFN1110-3": 3, "DFN2510": 10,
                "DFN2020": 6, "DFN3030": 8, "SOT-5X3": 5, "SOT-9X3": 3}
    for k, v in defaults.items():
        if k in t:
            return v
    return None


def classify_ti_package(ti_pkg_token, pin_val=None):
    """Canonical code for a TI package name token (+optional pin count),
    in the same code space as classify_digikey_package."""
    norm_u = normalize_package(ti_pkg_token).upper()
    pins = _infer_pins_from_ti_pkg(ti_pkg_token, pin_val)

    if norm_u.startswith("SOD523"):
        return "SOD523_2"
    if norm_u.startswith("SOD323"):
        return "SOD323_2"
    if norm_u.startswith("DFN0603"):
        return "DFN0603_2"
    if norm_u.startswith("X2SON"):
        return f"X2SON_{pins}" if pins else "X2SON_4"
    if norm_u.startswith("DFN1006"):
        return f"DFN1006_{pins}" if pins else "DFN1006_2"
    if norm_u.startswith("DFN1616"):
        return "DFN1616_6"
    if norm_u.startswith("DFN1110"):
        return "DFN1110_3"
    if norm_u.startswith("DFN2020"):
        return "DFN2020_6"
    if norm_u.startswith("DFN2510"):
        return "DFN2510_10"
    if "SOT886" in norm_u or "SOT-886" in str(ti_pkg_token).upper():
        return "SOT886_6"
    if norm_u.startswith("USON"):
        return "USON_6"
    if norm_u.startswith("DFN3030"):
        return "DFN3030_8"
    if norm_u.startswith("DSBGA"):
        return "DSBGA_4"
    if norm_u.startswith("SC703"):
        return "SC703_3"
    if norm_u.startswith("SC706"):
        return "SC706_6"
    if norm_u.startswith("SOT233"):
        return "SOT233_3"
    if norm_u.startswith("SOT234"):
        return "SOT234_4"
    if norm_u.startswith("SOT235"):
        return "SOT235_5"
    if norm_u.startswith("SOT236"):
        return "SOT236_6"
    if re.match(r"SOT5\d3", norm_u) or norm_u == "SOT563":
        return "SOT523_2" if pins == 2 else "SOT553_5"
    if re.match(r"SOT9[\dX]3", norm_u):
        return "SOT9X3_3"
    if norm_u.startswith("UQFN"):
        if pins == 14:
            return "UQFN_14"
        if pins == 10:
            return "UQFN_10"
        return None
    if norm_u.startswith("WQFN"):
        return "WQFN_12"
    if norm_u.startswith("WSON"):
        if pins == 6:
            return "WSON_6"
        if pins == 15:
            return "WSON_15"
        return None
    if norm_u in ("SMA", "SMB", "SMC", "SOD123", "SOD128", "SOD123F"):
        return f"{norm_u}_2"
    return None


def ti_canonical_set(ti_pkg_cell, pin_val=None):
    """A TI 'Package name' cell may list several packages (comma-separated).
    Return the set of canonical codes AND normalized strings for all tokens."""
    codes, norms = set(), set()
    if ti_pkg_cell is None:
        return codes, norms
    for token in str(ti_pkg_cell).split(","):
        token = token.strip()
        if not token or token == "-":
            continue
        c = classify_ti_package(token, pin_val)
        if c:
            codes.add(c)
        n = normalize_package(token)
        if n:
            norms.add(n)
    return codes, norms


def packages_match(comp_canonical, comp_display, ti_pkg_cell, ti_pin_val=None):
    """Decide whether a competitor package matches a TI package cell.
    Uses canonical codes first (pin-aware), then a normalized-string fallback."""
    ti_codes, ti_norms = ti_canonical_set(ti_pkg_cell, ti_pin_val)

    if comp_canonical and comp_canonical in ti_codes:
        return True
    # canonical without pin suffix (body-only) equality
    if comp_canonical:
        comp_body = comp_canonical.rsplit("_", 1)[0]
        if any(code.rsplit("_", 1)[0] == comp_body for code in ti_codes):
            # bodies equal; treat as match (pin differences handled in scoring)
            return True
    # normalized-string fallback for competitor display package(s)
    comp_norms = set()
    for tok in str(comp_display or "").split(","):
        n = normalize_package(tok)
        if n:
            comp_norms.add(n)
    if comp_norms & ti_norms:
        return True
    return False


# ---------------------------------------------------------------------------
# OPN generation
# ---------------------------------------------------------------------------
CANONICAL_SUFFIX_MAP = {
    "SOD523_2": "DYAR", "SOD323_2": "DYFR", "DFN0603_2": "DPLR", "X2SON_4": "DPWR",
    "DFN1006_2": "DPYR", "DFN1006_3": "DMXR", "DFN1616_6": "VEBR", "DFN1110_3": "DXAR",
    "DFN2020_6": "DRVR", "DFN2510_10": "DQAR", "SOT886_6": "DRYR", "USON_6": "DPKR",
    "DFN3030_8": "DRBR", "DSBGA_4": "YZFR", "SC703_3": "DCKR", "SC706_6": "DCKR",
    "SOT233_3": "DBZR", "SOT234_4": "DZDR", "SOT235_5": "DBVR", "SOT236_6": "DBVR",
    "SOT523_2": "DRLR", "SOT553_5": "DRLR", "SOT9X3_3": "DRTR", "UQFN_14": "RVZR",
    "UQFN_10": "RSER", "WQFN_12": "RSFR", "WSON_6": "DRSR", "WSON_15": "DSMR",
}


def generate_ti_opn(ti_base_part, ti_pkg_cell, ti_pin_val=None, is_automotive=False):
    """Append the package/pin suffix to a TI base part number, and Q1 for auto.
    Falls back to returning the base part if no suffix rule is known."""
    base = str(ti_base_part or "").strip()
    if not base:
        return base
    codes, _ = ti_canonical_set(ti_pkg_cell, ti_pin_val)
    suffix = None
    for c in codes:
        if c in CANONICAL_SUFFIX_MAP:
            suffix = CANONICAL_SUFFIX_MAP[c]
            break
    # if base already ends with the suffix or is a full orderable OPN, keep it
    opn = base
    if suffix and not base.upper().endswith(suffix):
        opn = f"{base}{suffix}"
    if is_automotive and not opn.upper().endswith("Q1"):
        opn = f"{opn}Q1"
    return opn
