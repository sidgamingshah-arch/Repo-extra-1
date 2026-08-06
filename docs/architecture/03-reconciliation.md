# Note→face reconciliation (Requirement 20)

The highest-value rule. Implemented as pure functions in `app/services/reconcile.py`
and exhaustively unit-tested in `tests/test_reconcile.py`.

## The rule

When a detailed item comes from a NOTE and the FACE has an overarching line that
references that note, the face aggregate must be adjusted by **subtracting** the note
detail(s) that are *also* ingested as their own template lines — otherwise the same
amount is counted twice (once as the face aggregate, once as the note component).

## Detection → `FaceNoteLink`

For each face `LineItem` with `note_refs`, look up the note in the `NoteIndex` and
**validate by amount** (note total vs face value within tolerance), classifying:

- `ONE_TO_ONE` — one face line references one note, note total == face.
- `NOTE_SPLITS_TO_MANY_FACE` — one note referenced by several face lines; partition
  the note's detail rows to each face by ontology mapping + amount (track `coverage`).
- `MANY_NOTES_TO_ONE_FACE` — several notes roll into one face line; dedupe details.
- `PARTIAL` — face = mapped detail + an unmapped "Other" remainder.

## Reconciliation (per basis × period, independent)

```
adjusted_face = raw_face_value
for detail in details that map to a distinct template line:
    adjusted_face -= detail.value      # signed, unit-normalized
reconciled = adjusted_face             # ALWAYS from raw → idempotent
residual   = raw_face_value - Σ(all note details)   # surfaced for review
```

Then assert template rollups and the accounting identity; failures downgrade the link
and push a `ReviewItem` with the discrepancy amount.

## Edge cases (all covered by the arithmetic + tests)

- **Signed details** — a negative detail (e.g. accumulated depreciation) is subtracted
  with its sign: `12,800 - (-2,200) = 15,000`. Sign errors here are doubly dangerous,
  so reconciliation is gated on sign confidence.
- **Dedup** — a detail referenced under two note refs is subtracted once (dedupe by
  detail id); a warning is recorded.
- **Partial → residual** — `reconciled` becomes the intended "Other/Residual" so totals
  still add up; a **negative** reconciled value is flagged as over-subtraction / a
  mapping or sign error.
- **Idempotency** — always computed from the raw value, never from an already
  reconciled figure, so re-running is safe.
- **Unit mismatch** — caller converts both sides to base units before subtracting
  (never subtract across unmatched unit contexts).
- **Tolerance** — `max(abs_eps, rel_eps × face)`; the residual delta is reported even
  when within tolerance, for audit.
- **No amount confirmation** — if the note total can't be computed (bad OCR), the link
  is proposed at low confidence for human confirmation rather than auto-subtracted.

The stage emits a `ReconciliationReport` (every link, the subtraction applied, failed
assertions) that feeds `validation` confidence.
