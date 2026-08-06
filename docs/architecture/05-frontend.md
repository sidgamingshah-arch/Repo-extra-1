# Frontend (React 18 + TypeScript, Vite) — implemented

Implemented in `frontend/` per the FinExtract design handoff (8 screens). Run with
`cd frontend && pnpm install && pnpm dev` alongside the backend; the Vite dev server
proxies `/api` to FastAPI. See `frontend/README.md` for the file map. The notes below
describe the architecture; a few advanced pieces (PDF.js bbox overlay, HyperFormula
worker) are represented by their design-equivalent here (a rendered "paper" source
view and a stored formula string) and deepen as the live extraction pipeline lands.

## State & libraries

- **TanStack Query** for durable server data; **Zustand** for the high-frequency,
  ephemeral cross-highlight/UI layer (active/hovered cell, zoom, filters, dirty edits)
  — deliberately not Redux, to avoid re-rendering the viewer on every hover.
- **React Router v6** with route-level code-split for the heavy PDF/grid bundles.
- **PDF.js** (direct, for the viewport transform), **AG Grid** (tree data + column
  groups + custom cell renderers), **HyperFormula** in a Web Worker (sandboxed,
  Excel-compatible recalc), **ExcelJS** (export), Tailwind + Radix, react-i18next.

## Routes

```
/  ·  /upload  ·  /documents/:id/progress (WS)  ·  /documents/:id/integrity (gate)
/documents/:id/review  (workspace)  ·  /queue  ·  /notes  ·  /export
/templates  ·  /templates/:id/edit  (editor + ontology upload)
```

## Signature screen — side-by-side hyperlinked viewer

Left: PDF.js canvas / `<img>` for scans. Right: template grid. Highlights are an
absolutely-positioned SVG overlay sharing the page's `relative` parent, so
**normalized [0..1] bboxes** derive pixel rects from live container size
(`ResizeObserver`) and stay aligned across zoom/rotation/DPR with no recompute — the
y-flip is normalized server-side so the client never touches it. Bidirectional focus
(`focusRequest` in Zustand) links grid ↔ viewer. Pages virtualized for 200+ page
filings.

## Signature screen — editable grid with formulas

AG Grid tree (sections → items → subtotals; pinned label/note columns; column groups
for consolidated/standalone). Formula bar + HyperFormula worker; display precedence
`computed → override → raw` so the machine's original value stays auditable.
Confidence shown as colorblind-safe color + badge with a low-confidence filter/sweep
mode. Units/currency switching is a **display-time transform only** — formulas operate
on stored source-unit numbers.

## Extraction mode — auto vs. confirm page scope

Chosen on the Upload screen (`extractMode` in the Zustand store, default **auto**).
In **auto** mode the pipeline detects statement pages and extracts in one pass: the
Integrity screen's forward action becomes **Extract now** → Workspace, and the top
stepper collapses to Upload → Integrity → Extract → Review → Export (the Page Scope
step is dropped). In **confirm** mode the Integrity action is **Detect statement
pages** → the Page Scope screen, where the user reviews/adjusts detected pages before
extraction. The choice is sent to the backend as `confirm_scope` on the extraction
run and persisted in the run's options.

## Other screens

Integrity report (routing gate before review), review queue (expected-vs-actual,
jump-to-cell, resolve/assign), notes tab (all notes + note-ref chips linking
face↔note), template/ontology editor (dnd tree + subtotal-rule builder + ontology
upload validated with Zod), export dialog. Client TS types mirror the backend model
1:1, each with a Zod schema at the API boundary.

## Riskiest UI parts

Bbox alignment across zoom/rotation/DPR (prototype first — normalized coords +
`ResizeObserver` + server-side y-flip); formula recalc at scale (Worker + AG Grid
transaction updates); keeping raw/override/formula/computed coherent with the units
transform (single `resolveDisplay`/`resolveNumeric` helpers); realtime consistency
(REST snapshot on reconnect); Excel formula fidelity (shared A1-translation module).
