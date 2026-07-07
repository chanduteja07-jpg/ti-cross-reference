# Cross-Reference Engine — Independent Verification Report

Scope: `crossref/engine.py`, `crossref/packages.py`, `crossref/data_layer.py`.
Method: all checks were re-derived from the written FORMULA and ALGORITHM
independently (a standalone script, not the engine's own tier/score code
paths, recomputed tier, hard-filter pass/fail, ranking order, and route
sanity from raw spec values), then diffed against what `find_alternatives()`
actually returned, for all 160 parts in `data/test.xlsx` against the 212-row
`data/ti_pool.csv`. Several results were additionally hand-traced with a
calculator to confirm the automated re-derivation itself is trustworthy.

## Overall verdict

**The FORMULA (tier classification) and ALGORITHM (hard filters + ranking)
in `engine.py` are implemented correctly and consistently.** Zero hard-filter
violations, zero tier mismatches, zero ranking-order violations, and zero
zener/TVS route leaks were found across all 437 returned alternative rows.

The issues found are **not in the funnel/scoring logic under test** — they
are in upstream spec extraction (`data_layer.py`) and in the test input file
itself:

1. A **regex bug in `data_layer.py`'s bidirectional-detection fallback**
   causes 24 of 160 competitor parts (15%) whose part number encodes
   bidirectional via a `...CAQ...`/`...CBQ...`/`(C)AQ` pattern to be
   mis-classified as `Unidirectional` instead of `Bidirectional`. This feeds
   wrong `Direction` into the (otherwise correct) engine, which faithfully
   applies its documented asymmetric direction rule to the bad input and
   surfaces a bidirectional TI part as the #1 pick — which is engine-correct
   given the badly-parsed input, but wrong given the real part.
2. **5 competitor part numbers in `test.xlsx`** do not exist in the DigiKey
   master under any recognizable key (1 Diodes part with no match by prefix,
   4 Nexperia part numbers that appear to have been corrupted into
   scientific-notation-style numeric strings, e.g. `934059000000`). These are
   test-data issues, not engine defects — `lookup_competitor` correctly
   returns `None` rather than fabricating a match.
3. Direction-mismatch top picks were also seen for 5 **genuinely**
   unidirectional competitor parts (no CA/CB marker at all, e.g. the Nexperia
   `PESD1LIN` family, onsemi `1SMA26AT3`). This is not a bug: the documented
   hard filter only excludes "competitor bidirectional but TI unidirectional"
   — the reverse (unidirectional competitor, bidirectional TI substitute) is
   intentionally allowed since a bidirectional device is a functional
   superset. Flagged below for human/business-rule review, not as a defect.

## Summary counts

| Metric | Count |
|---|---|
| Test parts (rows in test.xlsx) | 160 |
| Parts successfully looked up + crossed | 155 |
| Parts with lookup failure (no match / crash) | 5 |
| Total alternative rows returned (≤3 per part) | 437 |
| Parts with zero alternatives returned | 0 |
| Tier distribution of returned alts | S=20, Q=27, P=376, None=14 |
| **Hard-filter violations (Check 1)** | **0** |
| **Tier mismatches, engine vs. re-derived (Check 2)** | **0** |
| **Ranking (tier_rank, score) order violations (Check 3)** | **0** |
| **Zener↔TVS pool/route leaks (Check 4)** | **0** |
| Suspicious #1 picks — direction mismatch (Check 5) | 29 |
| … of which: `data_layer.py` CAQ/CBQ regex mis-parse | 24 |
| … of which: genuine uni-vs-bi (by-design, not a bug) | 5 |
| Suspicious #1 picks — Vrwm >30% off (Check 5) | 0 |

## Check 1 — Hard-filter compliance

Independently verified for every one of the 437 returned alternatives:
- (a) `ti_vclamp <= 3 × comp_vclamp` when both known
- (b) TI capacitance category ≤ competitor category + 1 (respecting the
  >10pF / unknown don't-care rule)
- (c) if competitor `Direction == Bidirectional` then TI must not be
  `Unidirectional`

**Result: 0 violations.** No alternative anywhere in the 160-part run
breaks any of the three documented hard filters. This includes the 24
CAQ-mislabeled parts — because the mislabeling makes the competitor spec say
"Unidirectional," rule (c) (which only fires on "competitor bidirectional")
does not trigger, so it doesn't count as a hard-filter violation; it shows up
instead as a plausibility flag in Check 5.

## Check 2 — Tier correctness

Recomputed S/Q/P/None from raw Vrwm, direction, capacitance category, ESD %,
and surge category for every returned alt, using an independent
re-implementation of the FORMULA text (not calling `classify_tier`).

**Result: 0 mismatches out of 437 alt rows.** Engine tier labels agree with
the from-scratch recomputation in every case.

Manual spot-checks (by hand, not script) corroborate this:
- `TPSMB39A` (Littelfuse, Vrwm 33.3V, package SMB, cap/ESD/surge unknown) →
  top alt `TVS3300`: package doesn't match (DSBGA/WSON vs SMB) so S/Q are
  unreachable; Vrwm diff = |33−33.3|/33.3 = 0.9% ≤ 25%; cap/ESD/surge
  don't-care since competitor values are unknown → **P**, matches engine.
- `MMBZ33VAT-Q` (Vrwm 26V, package TO-236AB/SOT-23-3, unidirectional) → top
  alt `TSM24B` (Vrwm 24V, SOT-23-3, uni-directional): package matches, Vrwm
  diff = |26−24|/26 = 7.7% ≤ 10%, polarity matches, comp cap/ESD/surge
  unknown → don't-care → **S**, matches engine.
- Several `SMF4L*CA-7` cases correctly fall to **None** because Vrwm diff is
  27–29% (e.g. comp 17V vs TI 12V = 29.4%), which exceeds even P's 25%
  tolerance — confirmed by hand arithmetic, matches engine (these are
  returned anyway because fewer than 3 higher-tier candidates exist for that
  part; see note under Check 5).

## Check 3 — Ranking

For every result list, confirmed consecutive alternatives are non-increasing
in `(tier_rank, score)`.

**Result: 0 out-of-order pairs** across all 155 result lists (437 rows).
Ranking is correctly formula-first (tier dominates score) in every case,
including the boundary case where `None`-tier rows (tier_rank 0) are
correctly placed after all S/Q/P rows within the same result list.

## Check 4 — Pool/route sanity (zener vs. TVS/ESD)

Cross-checked every returned TI part against the TI pool's own
`Clamping voltage (V)` column (empty ⇒ zener-like row, 61 of 212 pool rows;
non-empty ⇒ TVS/ESD-like, 151 of 212) against the competitor's classified
`Type` (Zener vs TVS/ESD, from `data_layer.py`).

**Result: 0 leaks.** No TVS/ESD-competitor part was ever crossed to a TI
zener-pool part, and no Zener-competitor part was ever crossed to a TI
TVS/ESD-pool part, across all 437 returned rows.

## Check 5 — Plausibility of #1 picks

Flagged any #1 pick with Vrwm >30% off from the competitor, or a direction
mismatch.

- **Vrwm implausibility: 0 cases.** No #1 pick anywhere exceeds 30% Vrwm
  deviation from its competitor (consistent with the hard filters' 25–30%
  ceilings).
- **Direction mismatch: 29 cases**, all in the form "competitor labeled
  Unidirectional, TI pick is Bi-directional" (the allowed direction of
  mismatch per the documented rule). Full list:

  **Group A — root cause: `data_layer.py` regex bug (24 parts).** Part
  numbers contain a `CA`/`CB` bidirectional marker immediately followed by a
  non-delimiter character (`Q`, or `)AQ` for one part), which the regex
  `C(?:A|B)(?:[-/]|$)` in `data_layer.py` fails to match because it requires
  `-`, `/`, or end-of-string right after `CA`/`CB`. Confirmed by direct
  comparison: `SMF4L17CA-7` → correctly `Bidirectional`, but the AEC-Q
  variant `SMF4L17CAQ-7` (same series) → incorrectly `Unidirectional`.

  | Competitor part | Engine #1 pick | Tier | Score |
  |---|---|---|---|
  | SMF4L17CAQ-7 | ESD601 | P | 5900 |
  | SMF4L18CAQ-7 | ESD601 | P | 6900 |
  | SMF4L24CAQ-7 | ESD701 | P | 6900 |
  | SMF4L33CAQ-7 | ESD801 | P | 5900 |
  | SMF4L40CAQ-7 | ESD801 | P | 5900 |
  | SMF4L12CAQ-7 | ESD501 | P | 6900 |
  | SMF4L14CAQ-7 | ESD501 | P | 5900 |
  | SMF4L15CAQ-7 | ESD501 | P | 5200 |
  | SMF4L20CAQ-7 | ESD601 | P | 5900 |
  | SMF4L11CAQ-7 | ESD501 | P | 5900 |
  | SMF4L16CAQ-7 | ESD601 | P | 5900 |
  | SMF4L22CAQ-7 | ESD701 | P | 5900 |
  | SMF4L26CAQ-7 | ESD701 | P | 5900 |
  | SMF4L36CAQ-7 | ESD801 | P | 6900 |
  | SMF4L13CAQ-7 | ESD501 | P | 5900 |
  | SMAJ15CAQ-13-F | ESD501 | P | 5200 |
  | SMAJ16CAQ-13-F | ESD601 | P | 5900 |
  | SMAJ18CAQ-13-F | ESD601 | P | 6900 |
  | SMAJ20CAQ-13-F | ESD601 | P | 5900 |
  | SMAJ22CAQ-13-F | ESD701 | P | 5900 |
  | SMAJ24CAQ-13-F | ESD701 | P | 6900 |
  | SMAJ33CAQ-13-F | ESD801 | P | 5900 |
  | SMBJ36(C)AQ-13-F | ESD801 | P | 6900 |
  | SMAJ12CAQ-13-F | ESD501 | P | 6900 |

  **Group B — genuinely unidirectional competitors, not a bug (5 parts).**
  These part numbers have no bidirectional marker at all; `Direction:
  Unidirectional` is the correct extracted spec. The engine's #1 pick is
  bidirectional because the documented hard filter only excludes the
  opposite case (bidirectional competitor → unidirectional TI excluded);
  a bidirectional TI substitute for a unidirectional competitor is allowed
  by design (functional superset). Recommend business-side review of
  whether this asymmetry is desired, but it is **not a deviation from the
  written algorithm**.

  | Competitor part | Engine #1 pick | Tier | Score |
  |---|---|---|---|
  | SZ1SMA26AT3G | TVS2701 | P | 5913 |
  | PESD1LIN,115 | ESD501 | P | 5200 |
  | PESD1LIN,135 | ESD501 | P | 5200 |
  | PESD1LIN | ESD501 | P | 5200 |
  | PESD1LINZ | ESD501 | P | 5200 |

## Lookup failures (5 of 160 parts — test-data issue, not engine logic)

| Competitor part | Manufacturer | Cause |
|---|---|---|
| D5V0Z1B2LP-7B | Diodes | No match in DigiKey master by exact/substring/prefix key (0 candidates share even a 6-char prefix) |
| 934059000000 | Nexperia | Part number appears corrupted to a 12-digit numeric string (likely Excel scientific-notation round-trip of a Nexperia code like "934-059..."); no match in master |
| 934060000000 | Nexperia | Same as above |
| 934065000000 | Nexperia | Same as above |
| 934070000000 | Nexperia | Same as above |

`lookup_competitor` behaves correctly here — it returns `None` rather than
guessing, and the engine/report pipeline does not fabricate a cross for
these rows.

## Additional observations (not defects)

- 14 of 437 returned alt rows carry `tier=None`. All are legitimately
  correct per the formula (verified in Check 2) — they occur only on parts
  where fewer than 3 candidates reach tier P, so the algorithm fills the
  remaining top-3 slots with the best surviving (hard-filter-passing but
  tier-failing) candidates. This is consistent with "top 3 are returned"
  in the algorithm description, but worth confirming with the business
  owner whether displaying sub-P "no confident cross" rows is the intended
  UX, versus showing fewer than 3 rows.

## Recommendation

The core funnel (`classify_tier`) and refiner (`score_candidate`,
hard filters, ranking) in `engine.py` faithfully implement the written
FORMULA and ALGORITHM — no changes recommended there based on this
verification. The one concrete defect worth fixing is the bidirectional
detection fallback regex in `data_layer.py`
(`re.search(r"(?:^|[-/])Q1?(?:[-/]|$)|AECQ", pn_up)` is unrelated; the
relevant line is `re.search(r"C(?:A|B)(?:[-/]|$)", pn_up)` used to set
`direction`), which should also match `CA`/`CB` followed by a trailing
qualifier letter (e.g. `Q`) before the delimiter — affecting 24 of 160
(15%) of this test set's competitor parts. No changes were made to any code
as part of this verification per instructions.
