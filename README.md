# TI Diode Cross-Reference Tool

Enter a competitor (non-TI) protection-diode part number and get the **top 3 TI
alternatives**, chosen by first applying the **Formula** (the S/Q/P funnel) and
then the **Algorithm** (the point-scoring refiner). Focus: ESD / TVS.

## Run it

Double-click **`run.command`** (macOS), or from a terminal:

```
cd "app"
python3 -m pip install -r requirements.txt
python3 app.py
```

Then open <http://127.0.0.1:5050>. First launch indexes the 94k master (~5 s), afterwards it is instant.

**One smart input box** handles all three:

- **A single part** – `PESD12VW1BCSF` (optionally add the manufacturer to disambiguate).
- **A list** – `SMBJ33A, DF2B7ASL, SP1003-01ETG`.
- **A pasted email / BOM** – drop an entire sales email or BOM table in; the tool auto-extracts the competitor part numbers and manufacturers.

For each competitor part it shows the **best TI cross**, a **replacement-type** badge (Drop-in / P2P / Functional), and a **spec-difference table** that highlights (green) where the TI part is better. A "not matched" panel lists anything it couldn't resolve (new part, zener/Schottky outside ESD-TVS scope, etc.) with a *Cross by specs* fallback — so it never guesses.

- **API** – `GET /api/cross?part=SMBJ33A&mfr=Diodes` returns JSON (crosses + replacement types + unresolved).
- **Batch CLI** – `python3 batch.py yourlist.xlsx` writes `ti_cross_results.xlsx`.

**Extraction accuracy** (Task 2, `python3 test_accuracy.py`): across 120 randomized emails/BOMs — **recall 98.6 %, precision 100 %** (F1 99.3 %). Precision 100 % = the fail-safe design never turns noise (BOM numbers, demand figures, TI answer OPNs) into a wrong cross; every candidate is validated against the real database before crossing.

## How it works

1. **Competitor lookup** (`crossref/data_layer.py`) finds the part in the 94k DigiKey master. Many rows in that export are column-shifted, so specs (Vrwm, clamping, package, direction) are parsed primarily from the reliable `Description` / `Detailed Description` text, with the parametric columns as fallback.
2. **Package common base** (`crossref/packages.py`) reduces both the competitor package and every TI package to one shared canonical code (`SOT233_3`, `DFN1006_2`, `SC703_3`, `SMB_2`, …) so matching ignores dashes, commas, spaces and JEDEC-vs-metric naming.
3. **Formula → Algorithm** (`crossref/engine.py`):
   - **Formula funnel** classifies each competitor↔TI pair as **S** (same package, tight), **Q** (same package, relaxed) or **P** (different package) using package / Vrwm / polarity / capacitance-category / ESD / surge rules.
   - **Algorithm** applies the hard filters (TI clamping ≤ 3× competitor; capacitance category ≤ competitor+1; competitor-bidirectional ⇒ TI-bidirectional) and scores survivors (+4500 package, +3000 channels, +2000 Vrwm≤5%, capacitance improvement, grade, surge, ESD, direction).
   - Results are ranked **formula-first**: tier (S→Q→P) then score. Auto/commercial duplicates are de-duplicated. Top 3 returned, each with a generated TI OPN.

## Data

- `data/digikey_master.csv` – the 94k competitor master (primary lookup source).
- `data/competitor_supplemental.csv` – 1,728 clean, direct-from-vendor parts (STMicro, Nexperia, Toshiba, Semtech, onsemi, Good-Ark) that fill gaps the DigiKey master misses (e.g. `PESD12VW1BCSF`). The lookup uses the master first (it has per-orderable package granularity), then falls back to this table.
  - **To add/refresh vendor data:** drop the exported files into `data/competitor_sources/` and run `python3 build_supplemental.py`. Adapters exist for the ST/Nexperia/Toshiba/Semtech/onsemi/Good-Ark export formats; add a new adapter in that script for a new vendor format.
  - If a part is in neither source, the app shows a **"Cross by specs"** form (Vrwm pre-filled from the name) so you can still cross it.
- `data/ti_pool.csv` – the 212-part TI protection portfolio (recommendation source). *The uploaded TI ESD parametric export could not be used as the pool because TI hid all orderable part numbers in it (0 of 104 rows had a name); this 212-part file is the one the algorithm references and it includes part numbers + pin counts.* To refresh, drop in a new TI parametric export **that includes the orderable part-number column** and re-save it here.

## Verification

`reports/package_audit.md` and `reports/cross_verification.md` hold the independent audits. Engine logic verified against the spec on all 160 test parts: 0 hard-filter violations, 0 tier mismatches, 0 ranking violations, 0 zener/TVS route leaks.
