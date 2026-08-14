# Note→face reconciliation (Requirement 20)

The highest-value rule. The arithmetic core is pure functions in
`app/services/reconcile.py`, exhaustively unit-tested in `backend/tests/test_reconcile.py`;
`app/stages/reconcile.py` wires it to the document model and is covered by
`tests/test_reconcile_stage.py`.

## The rule

When a detailed item comes from a NOTE and the FACE has an overarching line that
references that note, the face aggregate must be adjusted by **subtracting** the note
detail(s) that are *also* ingested as their own template lines — otherwise the same
amount is counted twice (once as the face aggregate, once as the note component).

## Detection → `FaceNoteLink` (`stages/link_notes.py`)

For each face `LineItem` with `note_refs` (or a bare `note_number`), the stage looks the
note up in an index of the extracted `NotesTable`s — a plain `{note_number: [tables]}` dict
built at the top of the stage; there is **no `NoteIndex` type**. It records a `FaceNoteLink`
carrying the note's detail item ids and labels the relationship from the citation counts:

- `ONE_TO_ONE` — one face line references one note, and no other face line cites it.
- `NOTE_SPLITS_TO_MANY_FACE` — several face lines cite the same note.
- `MANY_NOTES_TO_ONE_FACE` — the face line cites more than one note.

`LinkRelationship.PARTIAL` exists in the enum and is **not emitted by this stage**; the
"face = mapped detail + unmapped remainder" case shows up instead as a residual on the
reconciliation entry (below).

**Amount validation is not done here.** Linking is structural — a citation is a citation.
Whether the note actually *explains* the face figure is graded in the reconcile stage,
which is the stage that has the values.

## Reconciliation (per basis × period, independent)

```
adjusted_face = raw_face_value
for detail in details that map to a distinct template line:
    adjusted_face -= detail.value      # signed, unit-normalized
reconciled = adjusted_face             # ALWAYS from raw → idempotent
residual   = raw_face_value - Σ(all note details)   # surfaced for review
```

Only reported periods (`current` / `prior`) take part: extraction also emits positional
columns (`col2`, `col3`, … — maturity dates, coupon rates, an entity column) and comparing
a note total to one of those is meaningless.

### Grading the tie — three outcomes, not two

Most cited notes are **not a breakdown of the face figure**: "Profit before tax" lists
selected items charged and credited, a segment note analyses by division, a commitments
note is a schedule. None of them sum to the face line, and asserting a mismatch for each
would flood the queue with non-findings. So `services/reconcile.tie_status` grades:

- `tied` — the note total corroborates the face figure within tolerance.
- `untied` — it is close enough to be a claimed breakdown (`recon_corroboration_rel`,
  default 5%) and yet does not tie → a real finding, recorded in
  `ReconciliationReport.failed_assertions`.
- `unconfirmed` — the note is not a decomposition at all. Reported, never asserted as an
  error.

Only `tied` / `untied` may restate the face figure (`ExtractedValue.reconciled`); an
`unconfirmed` note leaves the reported value untouched.

**One question per (face line, note number).** A single note number routinely spans several
tables (continuation pages, sub-analyses). Exactly one `ReconciliationEntry` is recorded per
(face line, note, basis, period), using whichever table corroborates best — the one whose
residual is smallest.

Findings reach the analyst through `services/checks.check_reconciliation` over the stage's
entries, which `GET /documents/{id}/review` turns into queue cards; and through
`stages/confidence.py`, which caps the `validation` signal on values that participate in a
failed tie. There is no `ReviewItem` table — see
[02-data-model-and-schemas](02-data-model-and-schemas.md#validation-engine-feeds-the-review-queue).

## Edge cases (all covered by the arithmetic + tests)

- **Signed details** — a negative detail (e.g. accumulated depreciation) is subtracted
  with its sign: `12,800 - (-2,200) = 15,000`. Sign errors here are doubly dangerous,
  so reconciliation is gated on sign confidence.
- **A note's own subtotals are not details** — rows whose role is `SUBTOTAL`/`TOTAL` are
  skipped, and a detail mapped to the *face line's own* concept is not subtracted from
  itself.
- **Dedup** — a detail referenced under two note refs is subtracted once (dedupe by
  detail id); a warning is recorded.
- **Partial → residual** — `reconciled` becomes the intended "Other/Residual" so totals
  still add up; a **negative** reconciled value is flagged as over-subtraction / a
  mapping or sign error.
- **Idempotency** — always computed from the raw value, never from an already
  reconciled figure, so re-running is safe.
- **Unit mismatch** — caller converts both sides to base units before subtracting
  (never subtract across unmatched unit contexts).
- **Tolerance** — `max(abs_eps, rel_eps × face)` from `extraction.recon_abs_tolerance` /
  `recon_rel_tolerance`, read from configuration rather than the dataclass defaults so the
  Settings screen's knobs actually reach the code that names them; the residual delta is
  reported even when within tolerance, for audit.
- **No amount confirmation** — if a note table yields no comparable detail for a
  (basis, period) the stage records **no entry** for it rather than inventing one, and a note
  total that lands nowhere near the face figure is graded `unconfirmed`: the reported value
  stands and a human confirms, instead of an automatic subtraction.

The stage emits a `ReconciliationReport` (every entry, the subtraction applied, the failed
assertions) which feeds the confidence stage, the review queue and the notes screen.
