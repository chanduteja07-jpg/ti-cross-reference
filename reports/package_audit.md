# Package Normalization Audit — TI Diode Cross-Reference Tool

Scope: `crossref/packages.py` (canonical classifiers), `crossref/data_layer.py`
(competitor lookup), `crossref/engine.py` (matching/scoring). No code was
modified; this is a read-only audit run against the live data files
(`data/ti_pool.csv` — 212 TI parts, `data/digikey_master.csv` — 94,220
competitor rows, `data/test.xlsx` — 160 test competitor parts).

---

## Summary verdict

**The common base is directionally sound but has three concrete, high-impact
bugs that should be fixed before the package match is trusted for scoring.**

- The core JEDEC/metric equivalences (SOT-23↔SOT233_3, SOT-23-6↔SOT236_6,
  SC-70-3/SOT-323↔SC703_3, SOD-323↔SOD323_2, SOD-523↔SOD523_2,
  0201/0603↔DFN0603_2, DO-214AA/AB/AC↔SMB/SMC/SMA) all check out — the
  competitor classifier (`classify_digikey_package`) and the TI classifier
  (`classify_ti_package`) agree on the same canonical code in every case
  tested.
- However, **`classify_digikey_package` has no rule for "TO-236AB"** (the
  JEDEC alias for SOT-23, used pervasively by Nexperia and NXP), so it
  returns `Canonical Package = None` for roughly 216 rows in the 94k master
  (all 12 TO-236AB parts in the 160-part test set included). The match still
  usually survives in practice only because `packages_match()` has a
  secondary normalized-string fallback that happens to catch it — but the
  canonical field itself is wrong, and the fallback is a strictly weaker check.
- **SOD-882 is misrouted to DFN0603_2 (0.6×0.3 mm body) instead of DFN1006_2
  (1.0×0.6 mm body)** — this is the exact defect the audit brief asked me to
  check for, and it is present. It stems from a single line
  (`packages.py:158`) that lumps the "SOD882"/"SOD-882" dimension alias into
  the 0603 branch instead of the 1006 branch.
- **A bare "0402" supplier package string is not recognized at all** by
  `classify_digikey_package` (returns `None`), even though "0402" is the EIA
  equivalent of the 1.0×0.6 mm / DFN1006 body and `normalize_package()`
  (a different, lower-authority function used only for display/fallback)
  does recognize it. 75 rows in the master carry exactly `Supplier Device
  Package == "0402"` and all 75 get `Canonical Package = None`.
- **"SC-70-5" (a real, 19-row JEDEC package, 5-pin) is misclassified as
  SC703_3 (3-pin)** in `classify_digikey_package` because of an overly broad
  regex fallback.
- Two TI-side gaps exist that matter less: `SOT-9X3` never classifies (dead
  regex — looks for a digit where the token has a literal "X"), and multi-body
  TI cells like `WSON,USON,SOT-5X3` silently drop the WSON option when the
  row's single "Pin count" value (e.g. 5) doesn't match WSON's accepted pin
  counts (6 or 15), because every comma-separated token is classified with
  the *same* pin count.

None of these bugs crash the tool — they degrade to `None`/fallback behavior
— but they mean the canonical-code layer is less reliable than it looks, and
at least one (SOD-882) can actively steer a match to the *wrong* TI package
family rather than just failing to match.

---

## 1. Unmapped / mis-mapped TI "Package name" tokens

212 TI rows, 35 distinct `Package name` cells, 26 distinct individual tokens
after splitting on comma. Each token was run through `classify_ti_package(token, pin)`
using the row's actual `Pin count` (first value when multiple were listed).

| Token | Pin(s) seen | Result | Verdict | TI parts affected |
|---|---|---|---|---|
| `SOT-9X3` | 3 | `None` | **Bug** — dead regex | `TPD2EUSB30A`, `TPD2EUSB30` (and co-listed in `TPD2E28A` via `SOT-23-3,SOT-9X3`) |
| `SOT-SC70` | 3 | `None` | **Gap** — no rule at all for this literal TI token | `BZX84WC33V`, `BZX84WC33V-Q1` |
| `CDIP` / `LCCC` | 8,20 | `None` | Correct — genuinely out of scope (through-hole/ceramic, not a surface-mount TVS/ESD body this tool targets) | `UC1611-SP` |
| `LGA (PicoStar)` | 3,4 | `None` | Correct-ish gap — no canonical rule for PicoStar LGA; row still gets `SC70-3` from the other comma token so the part isn't fully lost | rows with `LGA (PicoStar),SC70-3` |
| `<empty>` Package name cell | 6 | `None` | Correct — no package data to classify | `TPD5E003` |
| `WSON` (row pin=5) | 5 | `None` | **Bug (narrowing)** — WSON classifier only accepts pins 6 or 15; a 5-pin row context blanks out the WSON option even though WSON is only ever 6- or 15-pin in reality (the *row's* pin count belongs to a different co-listed body, not to WSON) | `TPD3E001` (`SOT-5X3,USON,WSON` @ pin cell `5,6`) |
| `UQFN` (row pin=10 or 12) | 10,12 | `None` | Same class of bug — `classify_ti_package` only accepts UQFN pins 14 or 10, and the ambiguous multi-value pin cell `10,12` fails `int(float("10,12"))`-style parsing further up so it never even reaches the pin check cleanly in some callers | `TPD6E001` (`UQFN,WQFN` @ pin `10,12`) |
| `VSSOP` | 6,10 | `None` | Correct gap — VSSOP has no canonical rule (not in the SOT/DFN/SON family), and no TI part in the pool depends solely on it (always co-listed with SC70-6/SOT-23-6/USON/WSON) | `TPD4E05U06` style rows with `SC70-6,SOT-23-6,USON,VSSOP` |

**Net effect:** of the 26 distinct tokens, 3 are genuine, defensible gaps
(CDIP/LCCC, LGA PicoStar, VSSOP — none of these have a sensible SOT/DFN/SON
canonical code and TI doesn't sell enough volume in them to justify one), 1
(`SOT-9X3`) is a clear bug with an easy fix, 1 (`SOT-SC70`) is a bug/gap that
should probably map to `SC703_3` since "SOT-SC70" is just TI's naming for the
SC-70 body, and 2 more (`WSON`, `UQFN` in multi-body cells) reveal a
structural issue: **`ti_canonical_set` applies one row-level pin count to
every comma-separated package token**, which is wrong whenever the tokens
represent different physical body/pin-count combinations (very common in TI's
"available in multiple packages" cells).

Rows where **every** token resolves to `None` (i.e., the part has zero
matchable canonical codes despite non-empty codes existing elsewhere in a
comma cell):

```
BZX84WC33V      Package='SOT-SC70'      pin=3   -> no codes
BZX84WC33V-Q1   Package='SOT-SC70'      pin=3   -> no codes
TPD5E003        Package=''              pin=6   -> no codes
TPD2EUSB30A     Package='SOT-9X3'       pin=3   -> no codes
TPD2EUSB30      Package='SOT-9X3'       pin=3   -> no codes
UC1611-SP       Package='CDIP,LCCC'     pin=8,20-> no codes
```

These 6 TI parts are **completely invisible to package-based matching** —
they can only ever be reached via the Vrwm-proximity fallback (`P` tier) in
`engine.find_alternatives`, never via `S`/`Q` tier package matches, even
though `BZX84WC33V`/`TPD2EUSB30*` do have a real, common SMT package.

---

## 2. Competitor packages with `Canonical Package == None` (160-part test set)

Ran `crossref.data_layer.lookup_competitor(part, mfr)` for all 160 rows of
`data/test.xlsx` (`Competitor Name` used as manufacturer filter).

- 155 of 160 parts were found in the master; 5 were not found at all
  (`D5V0Z1B2LP-7B` / Diodes, and four Nexperia rows whose part numbers in the
  spreadsheet are malformed — `934059000000`, `934060000000`, `934065000000`,
  `934070000000` — almost certainly Excel-mangled versions of dotted part
  numbers like `934.059`; this is a **test-data quality issue**, not a
  package-normalization bug, but it's worth fixing the source spreadsheet).
- Of the 155 found, **23 rows have `Canonical Package == None`.**

| Display Package | Count in test set | Judgment | Notes |
|---|---|---|---|
| `TO-236AB` | 12 | **Gap / bug** | Should resolve to `SOT233_3`. JEDEC alias for SOT-23, TI stocks plenty of SOT-23-3 parts. See Bug #1 below. |
| `SOD-123W` | 8 | Correct (no TI equivalent) | Wide-body SOD-123 variant; TI pool has no `SOD-123W`/wide-body canonical, and none of the 212 TI parts use it. Legitimate gap, not a bug. |
| `D-Flat` | 2 | Correct (no TI equivalent) | Diodes Inc. proprietary flat-lead SMA-family body; not in TI's package vocabulary or the canonical code space. |
| `SMA-FL` | 1 | Correct (no TI equivalent) | Low-profile SMA variant (Littelfuse); same reasoning as D-Flat. |

**Judgment detail on TO-236AB:** this is the one row in the table that is a
real gap, not an intentional exclusion. `normalize_package("TO-236AB")`
already resolves this string correctly to `"SOT233"` (there's an explicit
rule for it at `packages.py:78`), but `classify_digikey_package` — the
function that actually produces `Canonical Package` — has no matching rule,
so the two functions disagree on the same input. Confirmed against the live
master: 216 rows across the full 94k-row file mention "TO-236AB" in their
description text (213 Nexperia, 3 NXP), so this is not a one-off — it
systematically zeroes out `Canonical Package` for a whole manufacturer's
SOT-23 product line whenever the row's `Supplier Device Package` column is
garbage (e.g. "AEC-Q100", a known column-shift artifact this file's own
docstring warns about) and the tool has to fall back to the text-parsed
package descriptor.

---

## 3. Common-base equivalence checks

Computed both `classify_digikey_package(supplier, case)` (competitor side)
and `classify_ti_package(token, pin)` (TI side) for each pair and compared.

| Equivalence | Competitor code | TI code | Result |
|---|---|---|---|
| SOT-23 → SOT233_3 | `SOT233_3` | `SOT233_3` | **PASS** |
| TO-236AB → SOT233_3 | `None` | `SOT233_3` | **FAIL** — competitor classifier has no TO-236AB rule (Bug #1) |
| SOT-23-6 → SOT236_6 | `SOT236_6` | `SOT236_6` | **PASS** |
| SC-70-3 → SC703_3 | `SC703_3` | `SC703_3` | **PASS** |
| SOT-323 (SC-70-3 alias) → SC703_3 | `SC703_3` | `SC703_3` | **PASS** |
| SOD-323 → SOD323_2 | `SOD323_2` | `SOD323_2` | **PASS** |
| SOD-523 → SOD523_2 | `SOD523_2` | `SOD523_2` | **PASS** |
| SOD-882 → DFN1006_2 | `DFN0603_2` | `DFN1006_2` | **FAIL** — competitor side routes SOD-882 to the wrong (smaller) body (Bug #2) |
| 0402 → DFN1006_2 | `None` | `DFN1006_2` | **FAIL** — competitor classifier doesn't recognize bare "0402" (Bug #3) |
| 1×0.6 dimension → DFN1006_2 | `DFN1006_2` | `DFN1006_2` | **PASS** (explicit dimension string works) |
| 0201 → DFN0603_2 | `DFN0603_2` | `DFN0603_2` | **PASS** |
| 0603 → DFN0603_2 | `DFN0603_2` | `DFN0603_2` | **PASS** |
| 0.6×0.3 dimension → DFN0603_2 | `DFN0603_2` | `DFN0603_2` | **PASS** |
| DO-214AA → SMB_2 | `SMB_2` | `SMB_2` | **PASS** |
| DO-214AC → SMA_2 | `SMA_2` | `SMA_2` | **PASS** |
| DO-214AB → SMC_2 | `SMC_2` | `SMC_2` | **PASS** |

**12 of 15 pass. 3 fail, all on the competitor (`classify_digikey_package`)
side** — the TI classifier was correct in every single equivalence tested.
The asymmetry is one-directional: bugs are concentrated in the DigiKey/
competitor classifier, not the TI classifier.

Additional check not in the original list but found during testing: **SC-70-5
(5-pin) incorrectly resolves to SC703_3 (3-pin)** on the competitor side —
see Bug #4.

---

## 4. Concrete bugs found

### Bug 1 — `classify_digikey_package` has no rule for "TO-236AB"
- **File / location:** `crossref/packages.py`, function `classify_digikey_package`
  (lines 143–242). The SOT-23 family block (lines 199–209) matches on
  `"SOT23" in sup...` or `"SOT143" in sup...`; `"TO-236AB"` → flattened
  `"TO236AB"` contains neither substring, so it falls through every rule and
  the function returns `None` at the bottom (line 242).
- **Exact input / output:** `classify_digikey_package("TO-236AB", "")` → `None`.
  Real example: `MMBZ33VAT-Q` (Nexperia) → `lookup_competitor` returns
  `Package='TO-236AB'`, `Canonical Package=None`, `Normalized Package='SOT233'`.
- **What it should be:** `SOT233_3` (same as plain "SOT-23"). Note
  `normalize_package()` already has this exact rule (`packages.py:78`,
  `flat in (..., "TO236AB", ...) → "SOT233"`) — `classify_digikey_package`
  just never consulted it or replicated it.
- **Blast radius:** 216 rows in the 94,220-row master (213 Nexperia, 3 NXP);
  12 of the 160 test parts.
- **Practical impact today:** Partially masked. `packages_match()` still
  matches these parts via its normalized-string fallback (`comp_norms &
  ti_norms`, using `Normalized Package` rather than `Canonical Package`), so
  `find_alternatives` for `MMBZ33VAT-Q` still produced a correct, `pkg_matched=True`,
  tier-`S` result against `TSM24B` (TI SOT-23-3) in spot-checking. But the
  `Canonical Package` field itself is wrong, the pin-aware body-equality
  branch in `packages_match` (which checks canonical codes, not normalized
  strings, and is intended to handle pin-count nuance) never fires for these
  parts, and any other code that reads `Canonical Package` directly (exports,
  dedup logic, future features) will see `None`.

### Bug 2 — SOD-882 routed to DFN0603_2 instead of DFN1006_2
- **File / location:** `crossref/packages.py:158`, inside `classify_digikey_package`:
  ```python
  is_0603_token = bool(re.search(r"(^|[^0-9])0603([^0-9]|$)", sup)) or _has_dim(sup, "SOD882", "SOD-882")
  ```
  This line ORs the SOD-882 alias into the *0603* detection flag, which then
  feeds the `DFN0603_2` return at line 167.
- **Exact input / output:** `classify_digikey_package("SOD-882", "")` → `DFN0603_2`.
- **What it should be:** `DFN1006_2`. SOD-882 is the ~1.0 × 0.6 mm body (same
  family as the "0402"/"1x0.6"/"1006" aliases handled correctly at line 172),
  not the ~0.6 × 0.3 mm DFN0603 body. This is confirmed by the TI-side
  classifier and by the equivalence table in the audit brief.
- **Blast radius:** Directly confirmed on 2 rows in the 160-part test set
  (`display_pkg == 'SOD-882'`); likely more in the full 94k master (not
  exhaustively counted, but the dimension alias is shared code so every
  SOD-882-labeled row in the master is affected the same way).
- **Practical impact:** A SOD-882 competitor part will be steered toward
  TI's DFN0603 parts (2-pin, ~0.6×0.3mm) as a "package match" (`pkg_matched=True`,
  `S`/`Q` tier eligible) when it should instead match DFN1006 (2-pin,
  ~1.0×0.6mm) parts — a real footprint mismatch, not just a missed match.
  This is worse than the TO-236AB bug because it doesn't fail safe; it
  actively produces a wrong "same package" claim.

### Bug 3 — bare "0402" supplier package string is unrecognized
- **File / location:** `crossref/packages.py`, `classify_digikey_package`,
  line 172: `if _has_dim(sup, "1x0.6", "1.0x0.6", "1006"): return "DFN1006_3" if ... else "DFN1006_2"`.
  There is no check for the literal token `"0402"` anywhere in the function
  (contrast with `normalize_package()` line 93, which explicitly includes
  `"0402" in norm` in its DFN1006 rule).
- **Exact input / output:** `classify_digikey_package("0402", "")` → `None`.
  `normalize_package("0402")` → `"DFN1006"` (disagreement between the two
  functions on the same string, same class of bug as #1).
- **What it should be:** `DFN1006_2`.
- **Blast radius:** 75 rows in the master have `Supplier Device Package`
  exactly equal to `"0402"` (verified: all 75 currently classify to `None`).
  None of the 160 test parts happened to hit this exact string, but it's a
  real, sizeable gap in the master.

### Bug 4 — "SC-70-5" (5-pin) misclassified as SC703_3 (3-pin)
- **File / location:** `crossref/packages.py:194-196`, `classify_digikey_package`:
  ```python
  if re.search(r"SC-?70-?3", sup) or "SOT323" in sup.replace("-", "") or (
      re.search(r"SC-?70", sup) and not re.search(r"SC-?70-?6", sup) and "SC88" not in sup.replace("-", "")):
      return "SC703_3"
  ```
  The parenthesized fallback clause matches any "SC-70..." string that isn't
  explicitly SC-70-6 or SC88, which incorrectly captures "SC-70-5".
- **Exact input / output:** `classify_digikey_package("SC-70-5", "")` → `SC703_3`
  (should not silently become 3-pin).
- **Blast radius:** 19 rows in the master carry exactly `Supplier Device
  Package == "SC-70-5"` (Würth Elektronik 82402374 / "5-TSSOP, SC-70-5,
  SOT-353" and several "Amazing" parts) — all 19 currently mis-tagged as
  `SC703_3`.
- **What it should be:** There's no `SC705_5`/SOT-353 canonical code defined
  in this codebase at all (checked `CANONICAL_SUFFIX_MAP` and both
  classifiers — SOT-353/SC-70-5 isn't represented). At minimum this should
  return `None` (or a new `SC705_5` code) rather than silently colliding with
  the 3-pin body. As-is, a 5-pin competitor part can register a false
  "package match" against a TI SC70-3 (3-pin) part.
- **Note:** this exact input also appears in the TI pool's own vocabulary
  indirectly — TI has no SC-70-5 parts in `ti_pool.csv`, so today this bug
  can't produce a false match *against a real TI part*, but it's still
  actively wrong and will bite the moment either the TI pool grows or the
  bug is fixed asymmetrically.

### Bug 5 — `classify_ti_package` never matches "SOT-9X3" (dead regex)
- **File / location:** `crossref/packages.py:320-321`:
  ```python
  if re.match(r"SOT9\d3", norm_u):
      return "SOT9X3_3"
  ```
  `norm_u` comes from `normalize_package("SOT-9X3")`, which (unlike its
  `SOT5X3 → "SOT563"` handling) has no digit-substitution rule for "9X3" and
  returns the literal string `"SOT9X3"`. The regex `SOT9\d3` requires a
  *digit* in the third position, but the normalized string still has the
  letter `X`, so the regex never matches.
- **Exact input / output:** `classify_ti_package("SOT-9X3", 3)` → `None`.
  Compare: `classify_ti_package("SOT-5X3", 5)` → `SOT553_5` (works, because
  `normalize_package` maps SOT-5X3-family strings to the literal digit string
  `"SOT563"` first).
- **What it should be:** `SOT9X3_3` (the code already exists — it's defined
  and used in `CANONICAL_SUFFIX_MAP` and in `classify_digikey_package`
  line 214 — this is purely a broken regex on the TI side).
- **Blast radius:** `TPD2EUSB30A`, `TPD2EUSB30` (package purely `SOT-9X3`) get
  zero canonical codes; `TPD2E28A`-style rows with `SOT-23-3,SOT-9X3` still
  get `SOT233_3` from the other token, so they're not fully blind, just
  missing one valid canonical option.
- **Secondary note:** even if this regex is fixed, `classify_digikey_package`'s
  competitor-side SOT-9X3 detection (`packages.py:214`,
  `_has_dim(sup, "1x1") and _has_pin_marker(combined, 3)`) requires an
  explicit "1x1" dimension string in the supplier package field. The one
  real DigiKey part found with this body uses `Supplier Device Package =
  "SOT-953"` (Littelfuse SP1004-04VTG), which matches neither side's rule —
  so this body is currently unmatchable from the competitor side regardless
  of the TI-side regex fix.

### Bug 6 (minor/structural) — one row-level pin count applied to every comma-separated TI package token
- **File / location:** `crossref/packages.py:341-357`, `ti_canonical_set()`:
  ```python
  for token in str(ti_pkg_cell).split(","):
      ...
      c = classify_ti_package(token, pin_val)
  ```
  `pin_val` is a single number (from the row's `Pin count` column, itself
  often a comma list collapsed to its first value by the caller). When a TI
  part is offered in multiple physical packages with different pin counts
  (e.g. `TPD3E001`: `SOT-5X3,USON,WSON` with `Pin count = "5,6"`), every token
  is classified against the *same* single pin value, so bodies whose pin
  count doesn't match that one value silently drop out of the canonical set.
- **Exact example:** `TPD3E001`, `Package name='SOT-5X3,USON,WSON'`,
  `Pin count='5,6'` → first-pin-parsed value is `5` → `ti_canonical_set`
  returns `{'SOT553_5', 'USON_6'}` (USON_6 survives because
  `classify_ti_package` ignores pins for USON and hardcodes `USON_6`) but
  **`WSON` disappears** (WSON classifier requires pins 6 or 15, and 5 ≠
  either, so it returns `None`) even though this part's WSON variant is
  presumably 6-pin in reality.
- **Impact:** narrows the matchable canonical set for any TI part listed in
  multiple package families with divergent pin counts; a competitor WSON-6
  part could fail to register as a package match against `TPD3E001` even
  though TI genuinely offers it in a WSON-6 body.

---

## Recommendations

1. **Fix Bug 2 (SOD-882) first — it's the only bug that produces an actively
   wrong "same package" claim rather than a missed match.** Move the
   `"SOD882"/"SOD-882"` alias out of the `is_0603_token` check (line 158) and
   into the DFN1006 dimension check (line 172), mirroring
   `normalize_package`'s already-correct handling.
2. **Fix Bug 1 (TO-236AB) — highest blast radius (216 master rows, 12/160
   test rows).** Add `"TO236AB"` (and ideally the DigiKey display forms
   `"TO-236AB"`) to the SOT-23 detection in `classify_digikey_package`
   alongside the existing `"SOT23"`/`"SOT143"` checks, so `Canonical Package`
   stops silently returning `None` and the code doesn't depend entirely on
   the weaker string-fallback path in `packages_match`.
3. **Fix Bug 3 (bare "0402")** — add a literal `"0402"` token check to the
   DFN1006 branch of `classify_digikey_package`, matching what
   `normalize_package` already does.
4. **Fix Bug 4 (SC-70-5)** — tighten the SC-70 fallback regex at
   `packages.py:194-196` to explicitly exclude `-5` (and any other digit)
   the same way it already excludes `-6`, so unrecognized SC-70-N variants
   return `None` instead of colliding with SC703_3. Consider whether a
   `SC705_5` canonical code is worth adding given DigiKey has 19+ such parts.
5. **Fix Bug 5 (SOT-9X3 regex)** — add a `normalize_package` rule that maps
   `SOT9X3`/`SOT-9X3` flat forms to a digit-bearing string (e.g. `"SOT953"`,
   mirroring the existing `SOT5X3 → "SOT563"` pattern), or simply change the
   `classify_ti_package` check from `re.match(r"SOT9\d3", norm_u)` to also
   accept the literal `"SOT9X3"`.
6. **Consider fixing Bug 6** by changing `ti_canonical_set` to accept a
   *set* of pin counts (parsed from the full, comma-split `Pin count` cell)
   rather than a single scalar, and try each token against all candidate pin
   counts before giving up. This is a more invasive change than the others
   and lower urgency since it only narrows (never wrongly widens) matches.
7. **Data hygiene, not a packages.py bug:** 4 of the 160 test rows
   (`934059000000`, `934060000000`, `934065000000`, `934070000000`, all
   Nexperia) are Excel-mangled numeric part numbers that will never match
   anything in the master; worth fixing at the spreadsheet/ingestion layer.
8. **No action needed** for `SOD-123W`, `D-Flat`, `SMA-FL`, `CDIP/LCCC`,
   `VSSOP`, and `LGA (PicoStar)` — confirmed these have no TI equivalent in
   the current 212-part pool, so `Canonical Package/None` is the correct
   answer for them today (revisit only if the TI pool grows to include those
   bodies).

---

## Spot-check: end-to-end package_match consistency (9 parts)

Ran `crossref.engine.find_alternatives` for a mix of DFN ESD, SOT-23 ESD,
SC-70/SOT-323, and SMA/SMB/SOD-123 TVS parts.

| Competitor part | Comp canonical | #1 TI alt | TI canonical set | `pkg_matched` | Consistent? |
|---|---|---|---|---|---|
| PESD24VS1UB,115 (Nexperia) | `DFN1006_2` | TVS2210 (`DFN1006`, pin 2) | `{DFN1006_2}` | True | Yes — comp canonical ∈ TI set |
| PESD2IVN24U-Q (Nexperia) | `SC703_3` | TPD2E2U06 (`SC70-3,SOT-5X3`, pin 3) | `{SC703_3, SOT553_5}` | True | Yes — comp canonical ∈ TI set |
| MMBZ33VAT-Q (Nexperia) | `None` (Bug 1) | TSM24B (`SOT-23-3`, pin 3) | `{SOT233_3}` | True | Matched only via the normalized-string fallback, not canonical codes — masks Bug 1 |
| SMAJ13AQ-13-F (Diodes) | `SMA_2` | TSD12 (`SOD323`, pin 2) | `{SOD323_2}` | False | Correctly falls to tier P — TI pool has no SMA-bodied part |
| SMBJ33A-7 (Diodes) | `SMB_2` | TVS3300 (`DSBGA,WSON`, pin 4) | `{DSBGA_4}` | False | Correctly falls to tier P — TI pool has no SMB-bodied part |
| SMF4L11CA-7 (Diodes) | `SOD123_2` | ESD501 (`DFN1006`, pin 2) | `{DFN1006_2}` | False | Correctly falls to tier P — no SOD-123 in TI pool |
| PESD5V0L1UL,315 (Nexperia) | `SOD323_2` | ESD411 (`DFN0603`, pin 2) | `{DFN0603_2}` | False | Correctly falls to tier P |
| SZSMF4L33CAT3G (Littelfuse) | `SOD123F_2` | TVS3301 (`DFN3030`, pin 8) | `{DFN3030_8}` | False | Correctly falls to tier P |
| TPSMB39A (Littelfuse) | `SMB_2` | TVS3300 (`DSBGA,WSON`, pin 4) | `{DSBGA_4}` | False | Correctly falls to tier P |

Result: **whenever `pkg_matched == True`, the competitor's canonical code (or
its normalized-string equivalent) is indeed present in the TI candidate's
canonical set** — the matching *logic* is internally consistent. The caveat
is the MMBZ33VAT-Q row: it only works because of the fallback path, and it
demonstrates concretely how Bug 1 is currently invisible in the UI/results
(the match still happens) while corrupting the `Canonical Package` field
underneath. The TI pool in this dataset simply doesn't stock SMA/SMB/DO-214-family
or SOD-123 bodies, so every DO-214/SOD-123 competitor test part correctly
falls through to tier P (different-package) rather than a false S/Q match —
that's expected behavior given the pool's contents, not a defect.
