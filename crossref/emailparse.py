"""
emailparse.py — Extract competitor part numbers (and manufacturer hints) from
free-form text: sales emails, BOM tables, "X vs Y" questions, pasted lists.

Fail-safe design: tokenize liberally, then VALIDATE every candidate against the
actual competitor database (lookup_competitor). Only tokens that resolve to a
real competitor part are crossed; everything else is surfaced as "unresolved"
so nothing is silently wrong or silently dropped.
"""
import re
from .data_layer import lookup_competitor, _norm_key

# Manufacturer aliases -> canonical name used as a lookup hint.
MFR_ALIASES = {
    "nexperia": "Nexperia", "diodes inc": "Diodes", "diodes": "Diodes",
    "littelfuse": "Littelfuse", "onsemi": "onsemi", "on semi": "onsemi",
    "on semiconductor": "onsemi", "stmicro": "STMicroelectronics",
    "st micro": "STMicroelectronics", "stmicroelectronics": "STMicroelectronics",
    "toshiba": "Toshiba", "semtech": "Semtech", "vishay": "Vishay",
    "comchip": "Comchip", "micro commercial": "MCC", "mcc": "MCC",
    "yangjie": "Yangjie", "panjit": "Panjit", "bourns": "Bourns",
    "ween": "WeEn", "good-ark": "Good-Ark", "goodark": "Good-Ark",
    "amazing": "Amazing", "rohm": "ROHM", "kyocera": "Kyocera",
    "protek": "ProTek", "wayon": "Wayon", "diotec": "Diotec",
    "microchip": "Microchip", "microsemi": "Microsemi", "maxim": "Maxim",
    "analog devices": "Analog Devices", "yageo": "YAGEO", "taiwan semi": "Taiwan Semiconductor",
    "galaxy": "Galaxy", "thinking": "Thinking Electronic", "bovate": "Bovate",
    "will semi": "Will", "umw": "UMW",
}

# A TI orderable number ends in a 4-letter package suffix (D??R style, or a few
# others), optionally + Q1. This precisely identifies TI OPNs *without* wrongly
# excluding competitor 'ESD…' parts (onsemi ESD5Z…, ST ESDA…, Amazing ESD…).
_TI_OPN_RE = re.compile(r"(D[A-Z]{2}R|YZFR|RVZR|RSER|RSFR|BQBR)(Q1)?$")

_STOPWORDS = {"DEMAND", "SHORTAGE", "REPLACEMENT", "ALTERNATE", "ALTERNATIVE",
              "PACKAGE", "VOLTAGE", "CLAMPING", "CAPACITANCE", "DROP-IN", "FUNCTIONAL"}

# Bare package names / spec fragments that look part-ish but aren't parts.
_NOISE_EXACT = {"SOD123", "SOD323", "SOD523", "SOD882", "SOD962", "SOD123F",
                "SOT23", "SOT323", "SOT363", "SOT143", "SOT563", "SOT666",
                "DFN1006", "DFN0603", "DFN2510", "DFN1110", "SMA", "SMB", "SMC",
                "DO214AA", "DO214AB", "DO214AC", "DO219AB", "SOD128"}


def _is_ti_opn(t):
    return bool(_TI_OPN_RE.search(t.upper()))


def _is_noise(t):
    u = t.upper().replace("-", "").replace(" ", "")
    if u in _NOISE_EXACT:
        return True
    if re.match(r"^\d+(\.\d+)?V", u):        # spec fragment like 30V0.5A, 5V5
        return True
    return False


def detect_mfrs(text):
    tl = " " + text.lower() + " "
    found = []
    for k, v in MFR_ALIASES.items():
        if k in tl and v not in found:
            found.append(v)
    return found


def _looks_like_part(t):
    if not (5 <= len(t) <= 30):
        return False
    if not re.search(r"[A-Za-z]", t) or not re.search(r"\d", t):
        return False
    if re.fullmatch(r"[\d.,]+", t):            # pure number (BOM/demand)
        return False
    if "@" in t or "http" in t.lower():
        return False
    if re.fullmatch(r"\+?\d[\d\-]{5,}", t):     # phone
        return False
    if t.upper() in _STOPWORDS:
        return False
    # too many lowercase letters in a row => an English word, not a part
    if re.search(r"[a-z]{5,}", t):
        return False
    return True


def _candidate_tokens(line):
    out = []
    for raw in re.split(r"[\s|\t]+", line):
        t = raw.strip().strip(".,;:()[]{}\"'`?! ")
        # a part may carry a trailing packaging code after a comma: DF2B7ASL,L3F
        for piece in (t, t.split(",")[0]):
            piece = piece.strip()
            if _looks_like_part(piece):
                out.append(piece)
    # de-dupe within the line, keep order
    seen, uniq = set(), []
    for t in out:
        k = _norm_key(t)
        if k and k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def _line_mfr(line):
    tl = line.lower()
    for k, v in MFR_ALIASES.items():
        if k in tl:
            return v
    return ""


def extract_parts(text, global_mfr=""):
    """Return (resolved, unresolved, mfrs).
    resolved: list of {"input","mfr","specs"} for tokens that matched a real part.
    unresolved: list of {"input","mfr"} that looked like parts but didn't match.
    """
    mfrs = detect_mfrs(text)
    resolved, unresolved, seen = [], [], set()
    for line in text.splitlines():
        lm = _line_mfr(line) or global_mfr
        for tok in _candidate_tokens(line):
            key = _norm_key(tok)
            if key in seen:
                continue
            if _is_ti_opn(tok) or _is_noise(tok):      # TI OPN or package/spec noise
                seen.add(key)
                continue
            specs = lookup_competitor(tok, lm)
            if specs is None and lm:
                specs = lookup_competitor(tok, "")
            if specs is None and mfrs:
                for m in mfrs:                          # try any mfr named in the email
                    specs = lookup_competitor(tok, m)
                    if specs:
                        lm = m
                        break
            seen.add(key)
            if specs:
                resolved.append({"input": tok, "mfr": lm or specs.get("Manufacturer", ""), "specs": specs})
            else:
                unresolved.append({"input": tok, "mfr": lm})
    return resolved, unresolved, mfrs
