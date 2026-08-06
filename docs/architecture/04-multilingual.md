# Multilingual support — input = output parity (Requirement 21)

The system must extract from documents in language L **and** display/export in
language L, for the *same* set of languages. Parity is enforced structurally, not by
convention.

**Seed set:** English (en), Chinese (zh), Arabic (ar — RTL), French (fr).

## Input side (extraction)

- **Language detection** (`stages/language.py`) sets the document `locale`, which
  drives OCR pack selection, number parsing, and ontology alias selection.
- **Locale-aware number parsing** (`services/numbers.py`) — decimal/thousands
  separators and grouping differ by locale (`1,234.56` US · `1.234,56` FR ·
  `1,23,456` Indian). Driven by the ontology's per-locale `NumberFormat`. A wrong
  separator silently corrupts values, so this is a *correctness* issue.
- **Per-locale ontology aliases** — `OntologyMapping.aliases_i18n` is locale-scoped;
  the matcher pulls the active locale's aliases plus the English set as a cross-lingual
  anchor, and a multilingual embedding model maps foreign labels to canonical keys.

## Output side

- **Localized canonical labels** — `TemplateNode.label_i18n`; `resolve_label(locale)`
  falls back to English.
- **Frontend i18n** — react-i18next for UI chrome; `Intl` for numbers/dates. **RTL**
  (Arabic): `dir="rtl"` flips grid column order and mirrors the viewer split; the
  normalized-bbox overlay is unaffected because coords stay in page space.
- **Localized export** — Excel/JSON labels + number formats in the chosen locale.

## Parity registry (the guarantee)

`schemas/languages.py` — a language is `supported` **only when all five** parity
artifacts exist for it:

1. OCR pack, 2. locale number-format rules, 3. ontology aliases for the active
template, 4. template `label_i18n`, 5. UI translation bundle.

`evaluate_parity(template, ontology)` computes this per locale; the `/languages` API
surfaces `supported` + `missing`. The UI offers only fully-supported languages for
both input and output, so the two sets are identical **by construction**. Adding a
language = supplying those five artifacts (data/assets), not an engineering change.

Verified by `tests/test_schemas.py::test_language_parity_full_for_seed_set` and
`tests/test_api.py` (all four seed languages report `supported` given a fully
localized template + ontology; Arabic reports `rtl=True`).

## Frontend (implemented)

The React app surfaces the parity directly:
- A **language switcher** in the top bar, populated from `GET /languages`
  (`frontend/src/components/shell/LanguageSwitcher.tsx`) — only fully-supported
  locales are offered, so the input and output language sets are identical.
- **i18n chrome** (`frontend/src/i18n.ts`) for the nav rail, pipeline stepper, and
  workspace toolbar/column headers in en/zh/ar/fr.
- **RTL** — selecting Arabic sets `dir="rtl"` on the document root, mirroring the
  whole layout (nav rail, source viewer, grid).
- **Localized output labels** — the workspace fetches statements with a `locale`
  param so line-item labels render in the chosen language, while the left source
  "paper" keeps the original (English) label — a direct visual demonstration of
  input→output parity. Verified by screenshotting all four locales
  (`test_localized_statement_labels` covers the backend resolution).

Statement-caption translations are standard IFRS/Ind-AS terminology for
demonstration; a native financial-language review is recommended before production.
