"""
test_accuracy.py — Randomized accuracy test for the email/text extractor.

Builds many synthetic sales emails / BOM tables that embed KNOWN competitor
parts amid realistic noise (manufacturer names, BOM numbers, demand figures,
TI answer OPNs, prose), then measures:

  Recall     = embedded parts that were extracted & crossed
  Precision  = extracted parts that were real (not noise/TI OPNs)
  Cross rate = extracted parts that produced a TI cross

Run:  python test_accuracy.py
"""
import random
import re
import pandas as pd

from crossref.data_layer import load_supplemental, load_master, _norm_key, lookup_competitor
from crossref.engine import find_alternatives
from crossref.emailparse import extract_parts

random.seed(7)

# ---- Build a pool of KNOWN, resolvable competitor parts to embed -------------
def _known_parts(n=220):
    parts = []
    sup = load_supplemental()
    if sup is not None:
        for _, r in sup.iterrows():
            p = str(r["Part"]).strip()
            if p and re.search(r"[A-Za-z]", p) and re.search(r"\d", p):
                parts.append((p, str(r["Manufacturer"]).strip()))
    # add real competitor parts from the test set (Diodes/Littelfuse/Nexperia)
    try:
        t = pd.read_excel("data/test.xlsx")
        for _, r in t.iterrows():
            p = str(r["Competitor Parts"]).strip()
            if p and p.lower() != "nan":
                parts.append((p, str(r["Competitor Name"]).strip()))
    except Exception:
        pass
    random.shuffle(parts)
    # keep only ones that actually resolve (so recall failures are extractor bugs)
    good = []
    for p, m in parts:
        if lookup_competitor(p, m):
            good.append((p, m))
        if len(good) >= n:
            break
    return good


# ---- Noise / distractor tokens that must NOT be treated as competitor parts -
TI_OPNS = ["ESD351DPYR", "TPD1E05U06DYAR", "ESD761DPYRQ1", "ESD701DPYR",
           "ESD321DYAR", "BZX884C39VDPYR", "TVS0500DRVR", "ESD451DPLRQ1"]
NOISE = ["1000129153", "-1,145,246", "368,715", "SBD", "JUL", "AUG", "SOD123",
         "30V0.5A", "MOLEX", "1830812133", "EC", "Q3-2026", "AEC-Q101"]

TEMPLATES = [
    "Hi Raj, {mfr} is asking for the best TI alternative for {parts}. Please advise replacement type. Thanks!",
    "Team, do we have a cross for {parts}? Competitor is {mfr}. Need spec comparison.",
    "From sales: customer wants 2nd source for {parts} ({mfr}). What is the closest TI part?",
    "BOM review — please cross the following {mfr} parts: {parts}. Include drop-in vs functional.",
    "{mfr} shortage on {parts}. Recommend TI equivalents with clamping/cap deltas.",
]

BOM_ROWS = "{bom}  {mfr}  {part}  {short}  {demand}  SBD  {tiopn}"


def _make_email():
    """Return (text, set_of_embedded_norm_keys)."""
    k = random.randint(1, 5)
    chosen = random.sample(KNOWN, k)
    embedded = {_norm_key(p) for p, _ in chosen}
    style = random.random()
    if style < 0.5:
        # prose email
        mfr = chosen[0][1]
        parts_str = ", ".join(p for p, _ in chosen)
        text = random.choice(TEMPLATES).format(mfr=mfr, parts=parts_str)
        # sprinkle distractors + a TI answer
        text += "\nCurrent TI suggestion: " + random.choice(TI_OPNS) + " " + " ".join(random.sample(NOISE, 3))
    else:
        # BOM table
        lines = ["Hi Raj, attached competitor BOM for review:",
                 "BOM NO   MFG   MFG P/N   JUN shortage   JUL demand   EC   TI Alternate"]
        for p, m in chosen:
            lines.append(BOM_ROWS.format(
                bom=random.randint(1000000000, 1999999999), mfr=m.upper(), part=p,
                short=f"-{random.randint(1000,999999):,}", demand=f"{random.randint(1000,999999):,}",
                tiopn=random.choice(TI_OPNS)))
        text = "\n".join(lines)
    return text, embedded


def run(n_emails=120):
    global KNOWN
    KNOWN = _known_parts()
    print(f"Pool of known resolvable competitor parts: {len(KNOWN)}")

    tot_embedded = tot_extracted_correct = tot_resolved = tot_false_pos = 0
    tot_crossed = perfect = 0
    for _ in range(n_emails):
        text, embedded = _make_email()
        resolved, unresolved, mfrs = extract_parts(text)
        resolved_keys = {_norm_key(r["input"]) for r in resolved}
        # also map resolved matched-device keys (a reel variant resolves to base)
        matched_keys = {_norm_key(r["specs"]["Device Name"]) for r in resolved}

        hit = 0
        for ek in embedded:
            # embedded part counts as found if its key OR its matched device is present
            if ek in resolved_keys or any(ek[:8] == rk[:8] for rk in resolved_keys | matched_keys):
                hit += 1
        tot_embedded += len(embedded)
        tot_extracted_correct += hit
        tot_resolved += len(resolved)
        # false positives: resolved parts that don't correspond to any embedded key
        for rk in resolved_keys:
            if not any(rk[:8] == ek[:8] for ek in embedded):
                tot_false_pos += 1
        # crosses produced
        for r in resolved:
            if find_alternatives(r["specs"]):
                tot_crossed += 1
        if hit == len(embedded):
            perfect += 1

    recall = tot_extracted_correct / tot_embedded if tot_embedded else 0
    precision = 1 - (tot_false_pos / tot_resolved) if tot_resolved else 0
    cross_rate = tot_crossed / tot_resolved if tot_resolved else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0
    print(f"\nEmails tested         : {n_emails}")
    print(f"Parts embedded        : {tot_embedded}")
    print(f"Recall  (found)       : {recall:6.1%}")
    print(f"Precision (no junk)   : {precision:6.1%}")
    print(f"F1                    : {f1:6.1%}")
    print(f"Cross produced        : {cross_rate:6.1%} of extracted")
    print(f"Emails 100% extracted : {perfect}/{n_emails} ({perfect/n_emails:.0%})")
    return recall, precision, cross_rate


if __name__ == "__main__":
    run()
