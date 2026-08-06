# FinExtract frontend

React 18 + TypeScript + Vite SPA implementing the FinExtract design handoff — the
8-screen financial-extraction workspace, wired to the FastAPI backend.

## Run (with the backend)

```bash
# terminal 1 — backend
cd ../backend && pip install -e ".[dev]" && uvicorn app.main:app --port 8000

# terminal 2 — frontend
cd frontend && pnpm install && pnpm dev      # http://localhost:5173
```

The Vite dev server proxies `/api` → `http://127.0.0.1:8000`, so the app is same-origin
in development. Production build: `pnpm build` (outputs `dist/`); serve `dist/` behind a
reverse proxy that forwards `/api` to the backend.

## Architecture

- **State:** TanStack Query for durable server data (`src/lib/queries.ts`); Zustand for
  ephemeral UI state — selection, toggles, edit-mode (`src/store.ts`).
- **Routing:** React Router v6; the nav rail and the pipeline stepper both drive the same
  8 routes (`src/screens/config.ts`).
- **Design tokens:** every color/font/radius/shadow/layout value from the handoff lives in
  `src/theme.ts` — components style with those tokens (no ad-hoc colors).
- **Primitives:** `src/components/ui.tsx` (Card, Pill, ConfidencePill, NoteChip, Button,
  Segmented, FieldChip, Toggle, StatusIcon) — the shared chrome every screen composes.
- **API client:** `src/lib/api.ts` (typed fetch wrapper + file-download for export).

## Screens (`src/screens/`)

| Route | File | Purpose |
|---|---|---|
| `/upload` | `Upload.tsx` | Source docs + template + ontology setup |
| `/integrity` | `Integrity.tsx` | Pre-flight document-integrity report |
| `/scope` | `Scope.tsx` | Statement-page detection / scoping |
| `/workspace` | `Workspace.tsx` | Side-by-side source ↔ template, edit + formulas |
| `/review` | `Review.tsx` | Checks-and-balances review queue |
| `/notes` | `Notes.tsx` | All extracted notes + note-to-face reconciliation |
| `/commentary` | `Commentary.tsx` | One-page financial analysis (ratios + strengths/risks) |
| `/template` | `Template.tsx` | Template tree + ontology rules (incl. netting rule) |
| `/export` | `Export.tsx` | Excel / JSON export with live preview |

Data is served by the backend's seeded demo project (Reliance Ind-AS FY24-25); uploaded
documents run through the real integrity/scope pipeline. See `docs/architecture/`.

## Access control & i18n

- **Roles** (top-bar switcher → `X-Role`): admin / reviewer / analyst. The nav is filtered
  by `GET /me`, routes are guarded (`RequireScreen`), and admin-only config controls are
  gated with `useCan(permission)` (`src/lib/rbac.ts`). Server-side enforced.
- **Languages** (top-bar switcher): en/zh/ar/fr; Arabic flips to RTL. UI chrome via
  `src/i18n.ts` (+ per-screen dicts in `src/i18n/screens/`); financial data localized by
  the backend `locale` param.
