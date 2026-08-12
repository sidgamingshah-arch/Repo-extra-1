# Testing & roadmap

## Testing strategy

- **Synthetic fixtures with known ground truth** (`backend/tests/fixtures/generate.py`)
  are the backbone — no real (sensitive) statements needed to measure accuracy:
  - native PDFs via reportlab with controlled face + notes, note refs, and
    deliberately reconcilable numbers;
  - XLSX via openpyxl with negative number-formats and a hidden sheet;
  - (designed) scanned variants by rendering + degrading (rotate/blur/noise/low-DPI)
    for OCR cases with exact expected coords; corrupt/encrypted variants for integrity.
- **Golden/unit tests per stage** — fixture → expected result. Current suite (32 tests):
  models, locale number parsing, the mapping ensemble, template/ontology validation,
  language parity, ingest routing + integrity, reconciliation arithmetic, and API
  endpoints.
- **Property-based tests** (Hypothesis, designed) for reconciliation — random but
  consistent face/note sets → assert rollups + accounting identity hold and that
  reconciliation is idempotent.
- **Adapter contract tests** (designed) — one fixture through every OCR/LLM adapter to
  prove downstream stages are adapter-agnostic; LLM adapters use record/replay mocks.

Run: `cd backend && pip install -e ".[dev]" && pytest -q`.

## Roadmap

**Backend** (✅ = done this phase)
1. ✅ Skeleton + contracts (models, pipeline, registry, ports, FastAPI scaffold).
2. ✅ Native ingest + per-page routing; integrity report; classification (heuristic).
3. ✅ Ontology mapping ensemble; locale number parsing; reconciliation arithmetic.
4. Native table reconstruction (pdfplumber) → `Table`; row/value extraction with
   provenance + two-level basis header.
5. Sign/unit normalization; note linking (amount-validated `FaceNoteLink`).
6. Reconciliation stage wiring + `ReconciliationReport`; validation engine +
   review queue; full extraction persistence (Statement/LineItem/... tables).
7. OCR path (PaddleOCR/PP-Structure adapter) into the same reconstruct stage.
8. ✅ Formula engine; export renderers (Excel/JSON); edit endpoints (no `If-Match` yet).
   Progress is polled, not pushed — the WebSocket stream is not built.
9. Confidence calibration; alternate adapters (Tesseract, TATR, local LLM); FX.

**Frontend**
Foundations → viewer core (bbox overlay) → grid core → grid↔viewer linkage →
editing + formulas → review queue → notes tab → consolidated/standalone → integrity
gate → template/ontology editor → export.

## Deferred, non-blocking decisions

- LLM: Claude API default vs self-hosted (adapter/config; decide with infra).
- Background worker (arq/RQ/Celery) and auth/multi-tenancy depth (decide with infra).
- FX rate source (`FxConverter` port left unbound).
