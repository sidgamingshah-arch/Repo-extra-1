# Data model, schemas & API

## Domain model (Pydantic, flows through the pipeline)

`app/core/models/` — the serializable model enriched stage-by-stage and returned by
the API:

- **`DocumentModel`** — pages, integrity report, tables, line items, notes, links,
  detected `locale`.
- **`PageSource`** — `kind` (face/notes/other), `source_kind` (native/scanned/mixed),
  geometry, and the native-vs-scanned feature values.
- **`Table` / `Cell`** — the convergence point: native and OCR pages both produce this.
- **`LineItem`** — `canonical_key`, `parent_id` (rollup tree), `role`, a dict of
  **`ExtractedValue` keyed by (basis, period)**, `sign_convention`, `note_refs`,
  `note_number`, `reconciliation_role`, `formula`, `ConfidenceVector`.
- **`ExtractedValue`** — `value_raw` (as printed) + `value` (sign-normalized) +
  `reconciled` (post-§20), `UnitContext`, `Provenance`, `ConfidenceVector`.
- **`Provenance`** — normalized `(page, bbox)` in original page space + recorded
  transforms; the basis for the side-by-side hyperlink.
- **`NotesTable` / `NoteItem`** and **`FaceNoteLink`** — backbone of §20.
- **`IntegrityReport`**, **`ReconciliationReport`**, **`RuleResult`**,
  **`ReviewItemModel`**.

## Persistence (SQLAlchemy)

`app/db/models.py` — this foundation persists `Document`, versioned
`TemplateVersion` / `OntologyVersion`, `ExtractionRun`, `FxRate`, `SettingOverride`
and `ReviewJudgement` (SQLite by default; Postgres via `FINEX_DATABASE_URL`).

**`ReviewJudgement`** is one human judgement on one review finding — the record that a
named person examined a finding's figures and recorded that they stand. It is keyed on
`(tenant_id, document_id, subject_key)`, where `subject_key` is the sha256 of the
finding's canonicalized *subject* rather than its id: two of the review-check builders
key their id on the extracted row's INDEX, so an id-keyed acceptance would silently move
onto a different line item after a re-run. `app/services/judgement.py` is the only place
in the codebase that hashes, and it holds the reasoning. A subject carries only what the
finding ASSERTS: no figure (a figure that moves means "stale, look again", not "different
finding") and nothing positional — not a row index, and not the rule id, because
`structural_checks._unique` disambiguates a repeated authored id with the entry's ordinal
among the rulebook's sentences, so deleting an unrelated sentence would otherwise
renumber a still-failing one and orphan its acceptance. Nor may a figure decide whether a
finding is EMITTED: a guard's `details.target` is derived from its violations, and while
it gated emission a failing guard could vanish from the queue by colliding with the
balance card's target. No column stores a digest, a
status or a count — all three are derived at serve time, because a derived value
persisted beside its source drifts from it.

Coverage is likewise NOT persisted: `run.result["structural"]` already holds every
relation row, and `app/services/coverage.py` recomputes the report from a stored run.

The full relational model (Statement, LineItem,
NotesTable, FaceNoteLink, ReviewItem, EditEvent, RuleResult, Export) is designed as:

- **Reproducibility** — each `ExtractionRun` pins document hash + template version +
  ontology version + engine id.
- **Concurrency** — optimistic `row_version` compare-and-swap + `If-Match`; conflicts
  return `409` with current state; append-only `EditEvent` log is the source of truth;
  `LineItem.value` is a materialized projection of machine value + applied edits.
- **Money** — `NUMERIC(28,4)` + a statement-level `units` multiplier (never float).
- **Migrations** — Alembic for DDL; each JSON payload carries a `schema_version` with a
  lazy payload-migrator.

## Template schema (`app/schemas/template.py`)

Ordered section→node tree. Subtotal/total nodes declare a `rollup {op, children}` so
subtotals are recomputed and compared to extracted values. Statement `identities`
(Assets = Liabilities + Equity, with tolerance) and `cross_statement_ties` (CF closing
cash = BS cash; P&L net income = equity movement) are declarative. Nodes carry
`label_i18n` for output parity. Duplicate canonical keys are rejected at load.

### Authoring a template as a workbook (`app/services/template_xlsx.py`)

JSON is the right shape for the pipeline and the wrong shape for the person deciding
what a spread should contain, so the template round-trips through Excel:
`GET /templates/{id}/xlsx` renders one row per line and `POST /templates/xlsx`
(multipart, admin) reads an edited workbook back as the **next version** of a template
key — nothing is overwritten, so an extraction that already ran still explains itself
against the version it used.

Two columns carry the decisions:

* **Kind** — `extracted` (mapped off the document), `calculated` (computed from other
  lines and never mapped), `heading`. A calculated line marked extracted would take a
  figure from the page instead of from its components, so this is the reviewable fact.
* **Calculated from** — the canonical keys a calculated line is made of, one per cell
  line. This is exactly what the structural checks recompute, so editing it changes
  what gets validated.

The reader is deliberately strict and names the offending row: a calculated line with
no components, an extracted line *with* components, a component key not in the sheet,
a duplicate canonical key, a line above its section heading, or an unknown statement
name are all `422` rather than a guess. Columns are matched on header TEXT, so a
reordered sheet or an extra notes column still reads correctly. `Identities` and
`Read me` sheets carry the statement equalities and the column contract.

## Reading a figure: one resolver (`app/services/periods.py`)

Every consumer of an extracted row — the statement view, the Excel export, the note
tables, the accounting checks, the ratios — has to answer the same two questions, and
answering them differently is how a prior-year figure gets printed under the current
year or a validated total stops being the total on screen. Both answers live here.

* `split_current_prior(values)` — a value that NAMES its period (`current`/`prior`)
  wins, and a period nothing was printed for stays `None`. The positional fallback
  (first value is current) applies **only** when no value names a period at all
  (columns read as `col0`/`col1`, or a matrix row's component columns). Filings print
  lines for one year only — a deposit pledged last year and released since — and the
  positional read reported that figure as this year's, inventing a current-year number
  the document never contained.
* `concept_value(group, basis, period)` — several printed lines legitimately map to one
  concept (three depreciation lines; a section's residual "Others"), so the default is
  their **sum**. A manual edit **replaces** it: entering 200 over a combined 150 shows
  200, not 350. Edits are recorded per `(basis, period)` in `edited_slots`, so
  correcting the consolidated current column does not restate the standalone or the
  prior one.

## Ontology schema (`app/schemas/ontology.py`)

Per canonical key: `aliases` + `aliases_i18n`, `keyword_hints`, `regex_hints`,
`exclude_hints`, `sign_rule`, `note_ref_hint`, `min_confidence_to_auto_accept`. Plus
`decomposition_rules` (define the face↔note tie + residual-as-"other"),
`number_format_by_locale`, and `global_rules`. The ontology is *data, not code* —
versioned and hot-swappable per job.

**Cross-check on upload** (`schemas/loader.py`): every ontology `canonical_key` and
`decomposition.face_key` must resolve against the template; rollups/identities must
reference existing node ids. Failures return `422` with the offending keys.

## Validation engine (feeds the review queue)

Unified `RuleDefinition` catalog from template rollups/identities,
cross-statement ties, and ontology decomposition rules, plus built-ins
(`confidence_threshold`, `required_present`). Each produces a
`RuleResult(status, expected, actual, difference, details)`; every `fail` upserts a
`ReviewItem` idempotently on `(run_id, rule_id, scope_key)`. Re-runs incrementally
after any edit touching a rule's operands.

## Formulas (safe)

No `eval`. Parse to a whitelisted AST (numbers, cell/`note:` refs, `+ - * /`,
`SUM/AVG/MIN/MAX/ABS/IF`); refs resolve only within the run. Per-run dependency graph
+ topological recompute; cycles surfaced as a cell error.

The Excel export does not build a live spreadsheet. A formula is carried for AUDIT, not
for recalculation: the flat extraction sheet has a `Formula` column holding the
expression as the analyst entered it (`build_rows_xlsx`), and the statement workbook
attaches it as a cell note on the row's label cell, beside the arithmetic of any
calculated line (`build_statement_workbook`). References are canonical line-item keys
(`bs_current_assets__inventories`), resolved server-side by `services/formula.py`, and
are never translated to cell addresses — the number in the cell is the value the server
computed.

## API (`/api/v1`, REST)

Implemented now: `POST /documents` (upload + integrity, hash-dedup),
`GET /documents/{id}`, `POST /documents/{id}/extractions`,
`GET /extractions/{run_id}` (status + progress — the client polls this once a second
while a run is `running`; there is no WebSocket),
`PATCH`/`DELETE /documents/{id}/line-items/{key}` (value, formula, comment,
revert-to-extracted), `GET /documents/{id}/export`
(`fmt=excel|json`, `layout=flat|statement`, `include=…`),
`GET /documents/{id}/review` (findings + their human judgements + the coverage
contract), `POST`/`DELETE /documents/{id}/review/judgements` (accept a finding, withdraw
an acceptance), `templates` + `ontologies` CRUD (with validation),
`GET /languages` (parity).

Not built: a push/WebSocket progress channel, `If-Match` optimistic concurrency on
edits, and `POST /statements/{id}/convert` (unit/currency conversion is a display
transform in the Workspace plus an export-time unit target).
