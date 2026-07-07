"""
build_supplemental.py — Normalize the manufacturer parametric exports in
data/competitor_sources/ into one clean competitor table:
    data/competitor_supplemental.csv

These come straight from the vendors' websites, so (unlike the DigiKey master)
their spec columns are clean and reliable. The lookup searches this table
first. Re-run this whenever you drop new/updated vendor files in.

Common output schema:
    Part, Manufacturer, Package, Vrwm, Vclamp, Capacitance, Channels,
    Direction, Grade, Type, Ipp, IEC42_kV, IEC45_A
"""
import os
import re
import csv
import warnings
warnings.filterwarnings("ignore")
from python_calamine import CalamineWorkbook

SRC = os.path.join(os.path.dirname(__file__), "data", "competitor_sources")
OUT = os.path.join(os.path.dirname(__file__), "data", "competitor_supplemental.csv")

COLS = ["Part", "Manufacturer", "Package", "Vrwm", "Vclamp", "Capacitance",
        "Channels", "Direction", "Grade", "Type", "Ipp", "IEC42_kV", "IEC45_A"]


# ---------------------------------------------------------------- helpers ----
def _num(v):
    """Extract a clean numeric string from messy cells: '+/-3.6', '± 30',
    '2.60 x 5.10', '-, ', '15.0'."""
    if v is None:
        return ""
    s = str(v).strip().strip(",").strip()
    if s in ("", "-", "-,", "N/A", "NA"):
        return ""
    m = re.search(r"[-+]?\d*\.?\d+", s.replace("±", "").replace("+/-", ""))
    return m.group(0) if m else ""


def _clean(v):
    if v is None:
        return ""
    s = str(v).strip().strip(",").strip()
    return "" if s in ("-", "-,", "—", "–", "N/A", "NA", "nan", "None") else s


def _vrwm_from_name(part):
    """Nexperia/generic: derive working voltage from the part name when the
    VRWM column is blank. PESD12V->12, PESD5V0->5.0, SMBJ33A->33."""
    p = str(part).upper()
    m = re.search(r"PESD(\d+)V(\d)?", p) or re.search(r"(?:SM[ABC]J|TPSMB|P6SM[ABC]J)(\d+)", p)
    if m:
        v = m.group(1)
        if m.re.groups >= 2 and m.lastindex and m.lastindex >= 2 and m.group(2):
            v = f"{v}.{m.group(2)}"
        return v
    return ""


def _dir(v):
    s = str(v).lower()
    if "bi" in s:
        return "Bidirectional"
    if "uni" in s:
        return "Unidirectional"
    return ""


def _rows_from_sheet(path, sheet=None):
    wb = CalamineWorkbook.from_path(path)
    sh = sheet or wb.sheet_names[0]
    return wb.get_sheet_by_name(sh).to_python()


def _hdr_index(header, *names):
    for i, h in enumerate(header):
        hl = str(h).lower()
        if any(n.lower() in hl for n in names):
            return i
    return None


def _emit(rec):
    return {c: rec.get(c, "") for c in COLS}


# --------------------------------------------------------------- adapters ----
def adapt_stmicro(path):
    d = _rows_from_sheet(path)
    hi = next(i for i, r in enumerate(d) if _hdr_index(r, "Part Number") is not None)
    h = d[hi]
    ix = {k: _hdr_index(h, *v) for k, v in {
        "part": ["Part Number"], "grade": ["Grade"], "pkg": ["Package"],
        "dir": ["Directionality", "Direction"], "vrwm": ["VRM (V) max", "VRM"],
        "vclamp": ["Clamping Voltage"], "cap": ["Capacitance"],
        "iec42": ["IEC 61000-4-2"]}.items()}
    out = []
    for r in d[hi + 1:]:
        if ix["part"] is None or not _clean(r[ix["part"]]):
            continue
        g = _clean(r[ix["grade"]]) if ix["grade"] is not None else ""
        out.append(_emit({
            "Part": _clean(r[ix["part"]]), "Manufacturer": "STMicroelectronics",
            "Package": _clean(r[ix["pkg"]]) if ix["pkg"] is not None else "",
            "Direction": _dir(r[ix["dir"]]) if ix["dir"] is not None else "",
            "Vrwm": _num(r[ix["vrwm"]]) if ix["vrwm"] is not None else "",
            "Vclamp": _num(r[ix["vclamp"]]) if ix["vclamp"] is not None else "",
            "Capacitance": _num(r[ix["cap"]]) if ix["cap"] is not None else "",
            "IEC42_kV": _num(r[ix["iec42"]]) if ix["iec42"] is not None else "",
            "Grade": "Automotive" if "auto" in g.lower() else "Commercial",
            "Type": "TVS/ESD"}))
    return out


def adapt_nexperia(path):
    d = _rows_from_sheet(path, "Products")
    hi = next(i for i, r in enumerate(d) if _hdr_index(r, "Type number") is not None)
    h = d[hi]
    ix = {k: _hdr_index(h, *v) for k, v in {
        "part": ["Type number"], "pkgn": ["Package name"], "pkgv": ["Package version"],
        "dir": ["Configuration"], "ch": ["Nr of lines"], "vrwm": ["VRWM"],
        "cap": ["Cd [typ]", "Cd"], "ipp": ["IPPM"], "iec42": ["VESD"]}.items()}
    out = []
    for r in d[hi + 1:]:
        if ix["part"] is None or not _clean(r[ix["part"]]):
            continue
        part = _clean(r[ix["part"]])
        vrwm = _num(r[ix["vrwm"]]) if ix["vrwm"] is not None else ""
        if not vrwm:
            vrwm = _vrwm_from_name(part)
        pkg = _clean(r[ix["pkgn"]]) if ix["pkgn"] is not None else ""
        if not pkg and ix["pkgv"] is not None:
            pkg = _clean(r[ix["pkgv"]])
        out.append(_emit({
            "Part": part, "Manufacturer": "Nexperia", "Package": pkg,
            "Direction": _dir(r[ix["dir"]]) if ix["dir"] is not None else "",
            "Channels": _num(r[ix["ch"]]) if ix["ch"] is not None else "",
            "Vrwm": vrwm, "Capacitance": _num(r[ix["cap"]]) if ix["cap"] is not None else "",
            "Ipp": _num(r[ix["ipp"]]) if ix["ipp"] is not None else "",
            "IEC42_kV": _num(r[ix["iec42"]]) if ix["iec42"] is not None else "",
            "Grade": "Automotive" if re.search(r"AEC|[-/]Q\b|Q1", part.upper()) else "Commercial",
            "Type": "TVS/ESD"}))
    return out


def adapt_toshiba(path):
    d = _rows_from_sheet(path)
    hi = next(i for i, r in enumerate(d) if _hdr_index(r, "Part Number") is not None)
    h = d[hi]
    ix = {k: _hdr_index(h, *v) for k, v in {
        "part": ["Part Number"], "pkg": ["Toshiba Package Name", "Package"],
        "dir": ["Configuration"], "ch": ["ProtectedLines"],
        "vrwm": ["Working peakreverse", "VRWM"], "cap": ["CT (Typ"],
        "iec42": ["Electrostatic", "IEC61000-4-2"], "ipp": ["Peak pulsecurrent", "Peak pulse"],
        "vclamp": ["Clamp voltage"], "aec": ["AEC-Q101"]}.items()}
    out = []
    for r in d[hi + 1:]:
        if ix["part"] is None or not _clean(r[ix["part"]]):
            continue
        aec = _clean(r[ix["aec"]]) if ix["aec"] is not None else ""
        out.append(_emit({
            "Part": _clean(r[ix["part"]]), "Manufacturer": "Toshiba",
            "Package": _clean(r[ix["pkg"]]) if ix["pkg"] is not None else "",
            "Direction": _dir(r[ix["dir"]]) if ix["dir"] is not None else "",
            "Channels": _num(r[ix["ch"]]) if ix["ch"] is not None else "",
            "Vrwm": _num(r[ix["vrwm"]]) if ix["vrwm"] is not None else "",
            "Capacitance": _num(r[ix["cap"]]) if ix["cap"] is not None else "",
            "IEC42_kV": _num(r[ix["iec42"]]) if ix["iec42"] is not None else "",
            "Ipp": _num(r[ix["ipp"]]) if ix["ipp"] is not None else "",
            "Vclamp": _num(r[ix["vclamp"]]) if ix["vclamp"] is not None else "",
            "Grade": "Automotive" if (aec and aec.lower() not in ("no", "-")) else "Commercial",
            "Type": "TVS/ESD"}))
    return out


def _adapt_csv(path, mapping, mfr, grade_fn=None):
    with open(path, encoding="utf-8-sig", errors="ignore") as f:
        rows = list(csv.reader(f))
    h = rows[0]
    ix = {k: _hdr_index(h, *v) for k, v in mapping.items()}
    out = []
    for r in rows[1:]:
        if ix.get("part") is None or ix["part"] >= len(r) or not _clean(r[ix["part"]]):
            continue
        def gv(key, num=True):
            i = ix.get(key)
            if i is None or i >= len(r):
                return ""
            return _num(r[i]) if num else _clean(r[i])
        part = _clean(r[ix["part"]])
        rec = {"Part": part, "Manufacturer": mfr, "Type": "TVS/ESD",
               "Package": gv("pkg", False), "Direction": _dir(r[ix["dir"]]) if ix.get("dir") is not None and ix["dir"] < len(r) else "",
               "Channels": gv("ch"), "Vrwm": gv("vrwm") or _vrwm_from_name(part),
               "Vclamp": gv("vclamp"), "Capacitance": gv("cap"),
               "Ipp": gv("ipp"), "IEC42_kV": gv("iec42"), "IEC45_A": gv("iec45")}
        rec["Grade"] = grade_fn(part) if grade_fn else "Commercial"
        out.append(_emit(rec))
    return out


def adapt_semtech(path):
    return _adapt_csv(path, {
        "part": ["Parts"], "pkg": ["Package"], "dir": ["Configuration Type", "Configuration"],
        "ch": ["Number of Lines"], "vrwm": ["VRWM MAX", "VRWM"], "cap": ["Cj (Typ", "Cj"],
        "ipp": ["IPP (A)"], "vclamp": ["VClamp"], "iec42": ["contact discharge", "IEC61000-4-2 (ESD) contact"]},
        "Semtech")


def adapt_onsemi(path):
    return _adapt_csv(path, {
        "part": ["Product Group"], "pkg": ["Package Type"], "dir": ["Direction"],
        "ch": ["Number of Lines"], "vrwm": ["VRWM Max", "VRWM"], "cap": ["C Max"]},
        "onsemi",
        grade_fn=lambda p: "Automotive" if p.upper().startswith("SZ") or re.search(r"AEC|[-/]Q\b", p.upper()) else "Commercial")


def adapt_webtable(path):
    return _adapt_csv(path, {
        "part": ["Part Number"], "pkg": ["Package"], "vrwm": ["Reverse Working", "Working  Voltage", "Reverse Working  Voltage"],
        "cap": ["Capacitance"], "iec45": ["Peak Pulse Current"], "iec42": ["Contact"]},
        "Good-Ark")


def adapt_by_manufacturer(path):
    """Curated multi-vendor sheet: one row per part, 'Company' = manufacturer."""
    d = _rows_from_sheet(path, "ESD Products")
    hi = next(i for i, r in enumerate(d) if _hdr_index(r, "Part Number") is not None)
    h = d[hi]
    ix = {k: _hdr_index(h, *v) for k, v in {
        "co": ["Company"], "part": ["Part Number"], "dtype": ["Device Type"],
        "dir": ["Config (Uni/Bi)", "Config"], "ch": ["Protected Lines", "Ch"],
        "vrwm": ["Vrwm"], "vbr": ["VBR"], "vclamp": ["Vclamp"], "ipp": ["IPP"],
        "cap": ["Capacitance"], "iec42": ["ESD IEC", "61000-4-2"], "pkg": ["Package"],
        "apps": ["Target Applications"], "notes": ["Notes"]}.items()}
    out = []
    for r in d[hi + 1:]:
        if ix["part"] is None or not _clean(r[ix["part"]]):
            continue
        part = _clean(r[ix["part"]])
        co = _clean(r[ix["co"]]) if ix["co"] is not None else ""
        blob = f"{part} {_clean(r[ix['apps']]) if ix['apps'] is not None else ''} {_clean(r[ix['notes']]) if ix['notes'] is not None else ''}".upper()
        dtype = (_clean(r[ix["dtype"]]) if ix["dtype"] is not None else "").lower()
        out.append(_emit({
            "Part": part, "Manufacturer": co or "Other",
            "Package": _clean(r[ix["pkg"]]) if ix["pkg"] is not None else "",
            "Direction": _dir(r[ix["dir"]]) if ix["dir"] is not None else "",
            "Channels": _num(r[ix["ch"]]) if ix["ch"] is not None else "",
            "Vrwm": (_num(r[ix["vrwm"]]) if ix["vrwm"] is not None else "") or _vrwm_from_name(part),
            "Vclamp": _num(r[ix["vclamp"]]) if ix["vclamp"] is not None else "",
            "Capacitance": _num(r[ix["cap"]]) if ix["cap"] is not None else "",
            "Ipp": _num(r[ix["ipp"]]) if ix["ipp"] is not None else "",
            "IEC42_kV": _num(r[ix["iec42"]]) if ix["iec42"] is not None else "",
            "Grade": "Automotive" if ("AUTOMOTIVE" in blob or "AEC" in blob or re.search(r"[-/]Q\b", part.upper())) else "Commercial",
            "Type": "Zener" if "zener" in dtype else "TVS/ESD"}))
    return out


# ------------------------------------------------------------------- main ----
ADAPTERS = [
    ("stmicro.xlsx", adapt_stmicro), ("nexperia_1.xls", adapt_nexperia),
    ("nexperia_2.xls", adapt_nexperia), ("toshiba.xlsx", adapt_toshiba),
    ("semtech.csv", adapt_semtech), ("onsemi.csv", adapt_onsemi),
    ("webtable_1.csv", adapt_webtable), ("webtable_2.csv", adapt_webtable),
    ("by_manufacturer.xlsx", adapt_by_manufacturer),
]


def main():
    all_rows, seen = [], set()
    for fname, fn in ADAPTERS:
        p = os.path.join(SRC, fname)
        if not os.path.exists(p):
            print("  (skip, missing)", fname); continue
        try:
            recs = fn(p)
        except Exception as e:
            print(f"  ERROR {fname}: {e}"); continue
        added = 0
        for rec in recs:
            key = re.sub(r"[\W_]+", "", rec["Part"].upper())
            if not key or key in seen:
                continue
            seen.add(key); all_rows.append(rec); added += 1
        print(f"  {fname:16s} -> {added} parts")
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} parts -> {OUT}")


if __name__ == "__main__":
    main()
