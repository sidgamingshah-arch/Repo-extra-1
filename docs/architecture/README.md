# FinEx architecture

Design & architecture for the financial-statement extraction platform.

## Contents

1. [Overview & requirements](00-overview.md) — the problem, decisions, and how all 21
   requirements map to components.
2. [Extraction pipeline](01-extraction-pipeline.md) — ingestion → integrity →
   classify → reconstruct → extract → map → normalize → link → reconcile → validate.
3. [Data model, template & ontology schemas, API](02-data-model-and-schemas.md).
4. [Note→face reconciliation](03-reconciliation.md) — the highest-value rule (§20).
5. [Multilingual parity](04-multilingual.md) — input = output for en/zh/ar/fr.
6. [Frontend](05-frontend.md) — side-by-side viewer, editable grid, review queue.
7. [RBAC & commentary](07-rbac-and-commentary.md) — roles/permissions and the analysis tab.
8. [Testing & roadmap](06-testing-and-roadmap.md).

## Decisions (fixed with the user)

- **Stack:** FastAPI (Python 3.11+) backend, React 18 / TypeScript frontend.
- **Extraction:** open-source OCR (PaddleOCR/PP-Structure, Tesseract fallback) + LLM,
  every external engine behind a swappable adapter (no mandatory cloud doc-AI).
- **Infra:** portable / decide-later — Postgres + S3-compatible object store behind
  ports; LLM/OCR/FX providers pluggable.
- **Languages (seed):** English, Chinese, Arabic (RTL), French.
