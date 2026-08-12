# Overview & requirements

## Problem

Analysts re-key financials from the *face* of statements **and** the *notes*,
reconcile them, and verify totals by hand — slow, error-prone, unauditable. FinEx
automates extraction while keeping a human in control: every number carries a
confidence score and a link to its source region, validation rules catch imbalances,
and analysts correct output (with formulas) before exporting.

## Data flow

```
Upload
  → Integrity report (gate: block corrupt/encrypted; warn on scans/rotation)
  → Extraction job (pipeline, async worker)
      ingest → integrity → language → classify → reconstruct → extract
             → map(ontology) → normalize(sign/units) → link notes → reconcile → validate
  → Progressive results (client polls GET /extractions/{run_id} while status = running)
  → Review workspace (side-by-side source ↔ editable grid)
  → Review queue (failed checks) → resolve
  → Export (Excel / JSON)
```

The pipeline runs in a background worker; every intermediate stage result is
persisted so stages are independently re-runnable and the UI hydrates progressively.

## Requirements → components (all 21)

| # | Requirement | Component |
|---|---|---|
| 1 | Excel / PDF / scanned extraction | `stages/ingest.py` (openpyxl, PyMuPDF, OCR adapter) |
| 2 | Face **and** notes | classify + notes model + reconcile |
| 3 | Output into predefined template | template schema + `LineItem.canonical_key` |
| 4 | Template addable from frontend | template editor + versioned template API |
| 5 | Ontology drives description-based extraction | ontology schema + `services/mapping.py` |
| 6 | Hyperlinked side-by-side view | `Provenance` (normalized bbox) + viewer overlay |
| 7 | Edit output in UI | editable grid + `EditEvent` audit log |
| 8 | Export Excel / JSON | `services/export.py` (openpyxl; formulas travel as a text column + cell notes, not live `=` cells) |
| 9 | Confidence per extraction | `ConfidenceVector` |
| 10 | Edits show formulas | `services/formula.py` — whitelisted-AST engine, server-side; the client sends/stores the formula string |
| 11 | Review queue on failed checks | validation engine → `RuleResult` → `ReviewItem` |
| 12 | Sign detection & normalization | `services/numbers.py` + normalize stage |
| 13 | Consolidated + standalone in one pass | `Basis`; values keyed by (basis, period) |
| 14 | Change units / currency | `UnitContext`; display transform + convert API |
| 15 | Note number per line item | `LineItem.note_number` + note chip |
| 16 | Separate notes tab | notes model + notes tab UI |
| 17 | Upfront document-integrity test | `stages/integrity.py` → `IntegrityReport` |
| 18 | Mixed scanned + native PDF | per-page routing in ingest |
| 19 | Locate face/notes pages first | classify stage; reconstruct targets them only |
| 20 | **Note→face subtraction reconciliation** | `FaceNoteLink` + `services/reconcile.py` |
| 21 | **Multilingual, input = output parity** | language stage + `schemas/languages.py` |

## Cross-cutting principles

- **Adapters everywhere** — OCR/LLM/embeddings/object-store/FX behind `Protocol`s,
  selected by config from a registry. "Decide infra later" costs nothing.
- **Provenance is first-class** — a value without `(page, bbox)` is a bug.
- **Deterministic first, LLM last** — cheap auditable heuristics; the LLM is a
  bounded, schema-constrained tie-breaker.
- **Versioned & reproducible** — each extraction run pins document hash + template
  version + ontology version + engine id.
