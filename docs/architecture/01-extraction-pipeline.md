# Extraction pipeline

Each stage is `run(doc, ctx) -> DocumentModel`, *enriching* an immutable-ish document
model. A BLOCKER integrity finding short-circuits the rest; everything else runs to
completion so all findings and partial results are available.

## Stages

1. **Ingest & route** (`stages/ingest.py`, implemented) — MIME/magic detection (not
   extension). Excel → openpyxl (one "page" per sheet); PDF → **per-page**
   native-vs-scanned detection using PyMuPDF text-char-count, text-area coverage, and
   image-area coverage; image → scanned. Mixed documents are handled per page, never a
   document-level flag.
2. **Integrity** (`stages/integrity.py`, implemented) — collects **all** findings into
   an `IntegrityReport` (BLOCKER/WARNING/INFO): corruption, password/encryption,
   no-pages, blank pages, rotation, inconsistent page dimensions, hidden Excel sheets,
   mixed-scan ratio. BLOCKER halts the pipeline; the report is returned to the UI as a
   gate before extraction.
3. **Language detect** (`stages/language.py`, implemented) — sets the document
   `locale` (drives OCR pack, number parsing, ontology aliases). Script-based
   heuristic for the seed set; `fasttext` pluggable behind the `lang` extra.
4. **Classify** (`stages/classify.py`, heuristic implemented) — locate FACE
   (BS/P&L/CF/Equity) vs NOTES vs OTHER via title regexes; layout features + LLM
   tie-break are TODO. Notes pages are kept (needed for §20).
5. **Reconstruct** (`stages/reconstruct.py`, scaffold) — native (pdfplumber rulings /
   PyMuPDF word coords) and scanned (OCR + table-structure adapter) both converge on
   the same `Table` model, so downstream stages are source-agnostic. Focuses face +
   notes pages only (Req 19). Coordinate transforms recorded so provenance maps back
   to the *original* page space.
6. **Extract** (`stages/extract.py`, scaffold) — rows → `LineItem`s with values keyed
   by (basis, period), note refs, unit context, and provenance. Uses the locale-aware
   parser in `services/numbers.py` and detects the two-level Consolidated/Standalone
   column header.
7. **Map (ontology)** (`stages/map_ontology.py` + `services/mapping.py`, ensemble
   implemented) — the multi-strategy matcher (below).
8. **Normalize** (`stages/normalize.py`, scaffold; paren/minus tier implemented in
   `services/numbers.py`) — sign detection + unit-context resolution.
9. **Link notes** (`stages/link_notes.py`, scaffold) — build `FaceNoteLink`s by note
   number, validated by amount.
10. **Reconcile** (`stages/reconcile.py` + `services/reconcile.py`, arithmetic
    implemented & tested) — the §20 subtraction (see [03-reconciliation](03-reconciliation.md)).
11. **Confidence + validate** (`stages/confidence.py`, scaffold; combination
    implemented on `ConfidenceVector`) — run rules → review-queue items.

## Mapping — a combination of methods, LLM as the key driver

`services/mapping.py` — mapping a printed label to a canonical concept is a **combination
of methods, none forced out**; the LLM is a *key driver*, not the sole authority. Each
method contributes and they corroborate one another:

1. **Exact / normalized lexical** — identity alias match; short-circuits (free, no tokens).
2. **Rule / fuzzy / embedding** — every method runs and contributes candidate evidence
   (and pre-shortlists concepts for the LLM when the ontology exceeds
   `extraction.llm_candidate_cap`).
3. **LLM semantic decision** (`extraction.llm_mapping`, default on) — the driver: shown
   the caption plus candidate concepts *with their criteria* (definition, include /
   exclude, confusable-with, value_scope) and the ontology's global policies + worked
   examples, it chooses by **meaning**. So "Amounts due from customers" → `trade_receivables`
   with no matching alias, and repeated "Others" captions disambiguate by section context.

**Combination policy:** exact wins outright; otherwise the LLM makes the call but is
**corroborated by the deterministic methods** — agreement nudges confidence up; a strong
lexical disagreement lowers it and flags review; the methods that agreed are recorded
(`MappingResult.agreement`). When no LLM is configured or it abstains, the deterministic
ensemble decides with the margin-over-runner-up accept policy. Every value also carries an
`allocation_status` (direct / child / residual / …) so parent-child handling is auditable.

Per-line LLM token usage accumulates on the pipeline context and is recorded on the
extraction run's audit-log entry. Winning method, confidence and per-strategy scores are
stored on the confidence vector; anything short of a confident, corroborated decision goes
to review, not a guess.

## Adapter ports

`ports/`: `OcrProvider`, `TableStructureProvider`, `LlmProvider` (structured JSON,
temp 0, Pydantic-validated), `EmbeddingProvider`, `ObjectStore` (local impl provided),
`FxConverter` (deferred). Concrete impls register into `Registry` keyed by id; config
selects them. Default engines are stubs that raise a clear message so a mis-wired
pipeline fails loudly rather than silently.
