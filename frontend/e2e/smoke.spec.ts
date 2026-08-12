import { test, expect, Page } from "@playwright/test";

const DCL = { waitUntil: "domcontentloaded" as const };

/** Log in via the demo quick-sign-in buttons (passwordless in demo mode). */
async function loginAs(page: Page, role: "admin" | "reviewer" | "analyst") {
  await page.goto("/", DCL);
  await page.getByRole("button", { name: new RegExp(role, "i") }).click();
  await expect(page.getByText(/FinExtract/)).toBeVisible();
}

/** Put the sample project into a known state. Whether it is loaded is a PERSISTED admin
 *  setting, so it carries across a restart and across suite runs — a test that needs it on or
 *  off has to say so rather than inherit whatever the last run left behind. */
async function setSampleLoaded(page: Page, want: boolean) {
  await page.goto("/settings", DCL);
  const row = page.getByTestId("seed-demo");
  await expect(row).toBeVisible({ timeout: 15_000 });
  if ((await row.getAttribute("data-on")) !== String(want)) {
    await row.click();
    await expect(row).toHaveAttribute("data-on", String(want), { timeout: 15_000 });
  }
}

/** Put the extraction thresholds back to what config.toml shipped.
 *
 * These are PERSISTED, so a test that changes one and walks away hands its override to the next
 * run — which is how the suite started failing on its second consecutive run. Any test touching
 * them restores them, and any test asserting "back to the default" establishes that baseline
 * first rather than trusting the value it happens to find. */
async function resetThresholds(page: Page) {
  await page.goto("/settings", DCL);
  const reset = page.getByTestId("ex-reset");
  await expect(reset).toBeVisible({ timeout: 15_000 });
  await reset.click();
  await expect(page.getByTestId("ex-save")).toBeDisabled({ timeout: 15_000 });
}

/** Open one template's detail page.
 *
 * Template & Ontology is two pages: an index of the templates that exist, and the structure tree
 * plus the ontology editors on a detail raised over it. Anything that drives an editor has to
 * click into a row first — and specifically into a row that HAS a rulebook, since a template no
 * ontology targets yet is legitimately read-only. */
async function openTemplateDetail(page: Page) {
  await page.goto("/template", DCL);
  const rows = page.getByTestId("tpl-row").filter({ hasNotText: "None yet" });
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });
  await rows.first().click();
  await expect(page.getByTestId("template-detail")).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: "serial" });

test("greenfield: the app is empty before any project is loaded", async ({ page }) => {
  await loginAs(page, "admin");
  // Establish the precondition instead of assuming it: "no project loaded" is now durable
  // state, so a previous run having loaded the sample must not decide this test's outcome.
  await setSampleLoaded(page, false);
  await page.goto("/workspace", DCL);
  await expect(page.getByRole("heading", { name: "No project yet" })).toBeVisible();
  await expect(page.getByText("Trade receivables")).toHaveCount(0);
});

test("admin can load the sample project and the workspace populates", async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/settings", DCL);
  await page.getByText("Load sample project").click();
  // Let the PATCH /settings + /me refetch settle before navigating.
  await expect(page.getByText("Load sample project")).toBeVisible();
  await page.waitForTimeout(600);
  await page.goto("/workspace", DCL);
  await expect(page.getByText("Trade receivables").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "No project yet" })).toHaveCount(0);
});

test("note references are hyperlinks to the All Notes screen", async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/workspace", DCL);
  await expect(page.getByText("Trade receivables").first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/notes/);
});

test("analyst uploads a document and views its extracted data with provenance", async ({ page }) => {
  await loginAs(page, "analyst");
  await page.goto("/upload", DCL);
  // The dropzone's hidden file input is real (browse is clickable).
  await page.setInputFiles('input[type="file"]', "e2e/fixtures/sample.pdf");
  await expect(page.getByTestId("doc-row").filter({ hasText: "sample.pdf" })).toBeVisible({ timeout: 15_000 });

  // Skip the integrity review and go straight to extraction for the just-uploaded document
  // (auto mode → the extraction view). The per-row "View" affordance was removed.
  await page.getByRole("button", { name: /Extract directly/ }).click();
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Extracted data" })).toBeVisible({ timeout: 15_000 });
  // Real extracted line item + click-to-source provenance from the native PDF.
  await expect(page.getByText("Trade receivables").first()).toBeVisible();
  // Click the value's source chip → the page renders with its bbox highlighted.
  await page.getByText(/^p\.1/).first().click();
  await expect(page.getByTestId("prov-highlight")).toBeVisible({ timeout: 15_000 });
});

test("analyst uploads a spreadsheet and gets Excel cell-level click-to-source", async ({ page }) => {
  await loginAs(page, "analyst");
  await page.goto("/upload", DCL);
  await page.setInputFiles('input[type="file"]', "e2e/fixtures/sample.xlsx");
  await expect(page.getByTestId("doc-row").filter({ hasText: "sample.xlsx" })).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: /Extract directly/ }).click();
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Extracted data" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Trade receivables").first()).toBeVisible();

  // Click a Sheet!Cell chip → the surrounding cells render with the target highlighted.
  await page.getByText(/!B\d/).first().click();
  await expect(page.getByTestId("cell-target")).toBeVisible({ timeout: 15_000 });
});

test("end-to-end: upload a new file → Run integrity check shows real results → extract", async ({ page }) => {
  test.setTimeout(180_000);   // full real path: upload → integrity → extract → scope → workspace → review → export
  await loginAs(page, "analyst");
  await page.goto("/upload", DCL);

  // Upload a brand-new file.
  await page.setInputFiles('input[type="file"]', "e2e/fixtures/sample.pdf");
  await expect(page.getByTestId("doc-row").filter({ hasText: "sample.pdf" })).toBeVisible({ timeout: 15_000 });

  // Hit "Run integrity check" → the Document Integrity screen must render THIS file's real
  // pre-flight results, not a blank/empty page.
  await page.getByRole("button", { name: /Run integrity check/ }).click();
  await expect(page).toHaveURL(/\/integrity/);
  await expect(page.getByRole("heading", { name: "Document integrity" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Pages", { exact: true })).toBeVisible();        // real stat, not EmptyState
  await expect(page.getByRole("heading", { name: "No project yet" })).toHaveCount(0);

  // Continue into the real extraction for the uploaded document.
  await page.getByRole("button", { name: /Extract now/ }).click();
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Extracted data" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Trade receivables").first()).toBeVisible();
  // Derived analysis (ratios / disclosures / notes) renders from the extraction.
  await expect(page.getByText("Ratios (computed)")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Disclosures")).toBeVisible();

  // Page Scope reads the REAL document's classified pages.
  await page.goto("/scope", DCL);
  await expect(page.getByRole("heading", { name: "Statement page detection" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("All pages")).toBeVisible();
  await expect(page.getByRole("heading", { name: "No project yet" })).toHaveCount(0);
  // Clicking a page opens the side-by-side rendered preview (real PDF page image).
  await page.getByTestId("scope-page").first().click();
  await expect(page.getByText(/Page preview/)).toBeVisible({ timeout: 15_000 });

  // Workspace renders the REAL extracted statement (its own line items, real filename).
  await page.goto("/workspace", DCL);
  await expect(page.getByText("Trade receivables").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Reliance Industries Ltd")).toHaveCount(0);         // no demo leakage
  // The left pane is the LIVE document viewer with click-to-source: selecting a row
  // scrolls the real page in and highlights the value's bounding box.
  await page.getByText("Trade receivables").first().click();
  await expect(page.getByTestId("prov-highlight")).toBeVisible({ timeout: 15_000 });

  // All Notes reads the REAL document's note references (make_native_pdf cites Note 15).
  await page.goto("/notes", DCL);
  await expect(page.getByText("N15").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "No project yet" })).toHaveCount(0);

  // Review runs on the REAL document (its own queue), not the demo project.
  await page.goto("/review", DCL);
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "No project yet" })).toHaveCount(0);

  // Export previews the REAL extracted rows (real data, not the demo Reliance sample).
  await page.goto("/export", DCL);
  await expect(page.getByRole("heading", { name: "Export" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("3410").first()).toBeVisible({ timeout: 15_000 });   // real extracted value
  await expect(page.getByText("4,23,180")).toHaveCount(0);                          // demo preview value absent
  await expect(page.getByText("Reliance Industries Ltd")).toHaveCount(0);           // demo chrome absent in real run
});

test("analyst cannot reach the config template screen but can select a template", async ({ page }) => {
  await loginAs(page, "analyst");

  // Template & Ontology is an admin-only configuration screen: it must NOT appear in the
  // analyst's nav, and a direct visit is redirected away (to the analyst's first screen).
  await page.goto("/workspace", DCL);
  await expect(page.getByText("Template & Ontology")).toHaveCount(0);
  await page.goto("/template", DCL);
  await expect(page).not.toHaveURL(/\/template/);

  // But the analyst still SELECTS a template on the Documents & Template (Upload) screen.
  await page.goto("/upload", DCL);
  await expect(page.getByText("Selected")).toBeVisible({ timeout: 15_000 }); // a template is active
  await page.getByRole("button", { name: "Choose another" }).click();
  const options = page.getByTestId("tpl-option");
  await expect(options.first()).toBeVisible({ timeout: 15_000 });            // real templates listed
  await options.first().click();
  // Selecting closes the picker (button returns to "Choose another") — selection is wired.
  await expect(page.getByRole("button", { name: "Choose another" })).toBeVisible();
});

test("the template screen is an index first: a row opens the detail, which dismisses back",
     async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/template", DCL);

  // PAGE 1 is a list of templates — the facts you pick between, not the structure of one of
  // them. The tree and the editors must not be on this page at all.
  const rows = page.getByTestId("tpl-row");
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });
  await expect(rows.first()).toContainText(/hkfrs/i);          // the template's name/key
  // Published state is one of the columns. WHICH state the first row is in depends on history —
  // a version published from an edited workbook is stored unpublished, and after any earlier run
  // of this suite that draft is the newest version — so assert on the row that must be published,
  // the seeded template, rather than on whichever version happens to sort first.
  await expect(rows.filter({ hasText: "Published" }).first()).toBeVisible();
  await expect(page.getByTestId("tpl-node")).toHaveCount(0);
  await expect(page.getByTestId("template-detail")).toHaveCount(0);
  // The line-item count is real: it is not in GET /templates, so the row has to go and get it.
  await expect(page.getByTestId("tpl-row-lines").first()).toHaveText(/^\d+$/, { timeout: 15_000 });

  // Filter the list. This is the list's own state — dismissing the detail must come back to the
  // list as it was, not to a freshly mounted one.
  await page.getByTestId("tpl-filter").fill("hkfrs");
  await expect(rows.first()).toBeVisible();

  // PAGE 2 opens on the row click, carrying the tree and the concept editor.
  await rows.first().click();
  await expect(page.getByTestId("template-detail")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("tpl-node").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByPlaceholder("New alias")).toBeVisible();
  await expect(page).toHaveURL(/[?&]template=/);              // reloadable / linkable

  // The starter ontology for THIS template is downloadable from its detail — it is derived from
  // one template, so it lives where a template is already chosen. Both halves of this feature
  // existed for a while with no UI at all and nothing noticed, because everything was exported
  // and tsc stayed quiet; these two assertions are what would have caught that.
  const [starter] = await Promise.all([
    page.waitForEvent("download", { timeout: 30_000 }),
    page.getByTestId("tpl-skeleton-download").click(),
  ]);
  expect(starter.suggestedFilename()).toMatch(/_ontology_skeleton\.json$/);

  // Dismissed → back on the index, still filtered.
  await page.getByTestId("tpl-detail-close").click();
  await expect(page.getByTestId("template-detail")).toHaveCount(0);
  await expect(page.getByTestId("tpl-filter")).toHaveValue("hkfrs");
  await expect(rows.first()).toBeVisible();
  await expect(page).not.toHaveURL(/[?&]template=/);

  // And the SHAPE any ontology must have is downloadable from the index, because it constrains
  // every one of them rather than any single template.
  const [schema] = await Promise.all([
    page.waitForEvent("download", { timeout: 30_000 }),
    page.getByTestId("tpl-schema-download").click(),
  ]);
  expect(schema.suggestedFilename()).toMatch(/^ontology_schema_v\d+\.json$/);
  await expect(page.getByTestId("tpl-schema-error")).toHaveCount(0);
});

test("admin edits the ontology inline and the new version persists", async ({ page }) => {
  await loginAs(page, "admin");
  await openTemplateDetail(page);

  // The real configured template renders its tree; pick the first editable concept.
  const nodes = page.getByTestId("tpl-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15_000 });
  await nodes.first().click();

  // Add an alias: type into the alias input and press Enter → it appears as a chip, and the
  // unsaved-changes bar shows up (edits are real local state, not decoration).
  const alias = `E2E alias ${Date.now()}`;
  const input = page.getByPlaceholder("New alias");
  await expect(input).toBeVisible();
  await input.fill(alias);
  await input.press("Enter");
  await expect(page.getByText(alias)).toBeVisible();
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  // Save → the server publishes a NEW ontology version and reports it back.
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible({ timeout: 15_000 });

  // The edit survives a full reload (it is stored, not just in local state).
  await page.reload(DCL);
  await expect(nodes.first()).toBeVisible({ timeout: 15_000 });
  await nodes.first().click();
  await expect(page.getByText(alias)).toBeVisible({ timeout: 15_000 });
});

test("admin edits the mapping CRITERIA and the new version persists", async ({ page }) => {
  await loginAs(page, "admin");
  await openTemplateDetail(page);

  const nodes = page.getByTestId("tpl-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15_000 });
  await nodes.first().click();

  // Criteria — not aliases — are what let an unfamiliar caption be mapped by MEANING, so they
  // have to be editable: add an inclusion criterion the same way an alias is added.
  const criterion = `E2E includes ${Date.now()}`;
  const include = page.getByTestId("criteria-include").getByRole("textbox");
  await expect(include).toBeVisible();
  await include.fill(criterion);
  await include.press("Enter");
  await expect(page.getByText(criterion)).toBeVisible();
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  // The value-scope choice is a real select over the four scopes the backend accepts.
  await expect(page.getByTestId("criteria-scope")).toBeVisible();

  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible({ timeout: 15_000 });

  // Stored, not just local: it comes back after a full reload.
  await page.reload(DCL);
  await expect(nodes.first()).toBeVisible({ timeout: 15_000 });
  await nodes.first().click();
  await expect(page.getByText(criterion)).toBeVisible({ timeout: 15_000 });
});

test("admin adds a netting rule and it persists; unknown keys are impossible", async ({ page }) => {
  await loginAs(page, "admin");
  await openTemplateDetail(page);
  await expect(page.getByTestId("tpl-node").first()).toBeVisible({ timeout: 15_000 });

  await page.getByTestId("netting-add").click();
  const target = page.getByTestId("netting-target");
  await expect(target).toBeVisible();
  // Keys are PICKED from the concepts that exist — there is no free-text key field to typo.
  const options = target.locator("option");
  expect(await options.count()).toBeGreaterThan(1);
  await target.selectOption({ index: 1 });

  // The draft rule is rendered last; fill and save it there (existing rules have the same
  // fields, so the locator has to be scoped to the row).
  const draft = page.getByTestId("netting-rule").last();
  const label = `E2E netting ${Date.now()}`;
  await draft.getByTestId("netting-label").fill(label);
  await draft.getByTestId("netting-save").click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible({ timeout: 15_000 });

  // Stored: after a reload the rule comes back (the server appends it, so it is the last row)
  // with the explanation we typed.
  await page.reload(DCL);
  await expect(page.getByTestId("tpl-node").first()).toBeVisible({ timeout: 15_000 });
  const rows = page.getByTestId("netting-rule");
  const saved = rows.last();
  await expect(saved.getByTestId("netting-label")).toHaveValue(label, { timeout: 15_000 });
  const before = await rows.count();

  // Clean up after ourselves so the rule doesn't leak into later runs (delete is two-step).
  await saved.getByTestId("netting-delete").click();
  await saved.getByTestId("netting-delete").click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible({ timeout: 15_000 });
  await expect(rows).toHaveCount(before - 1, { timeout: 15_000 });
});

test("an analyst gets no ontology editing affordances at all", async ({ page }) => {
  await loginAs(page, "analyst");

  // The authoring screen is admin-only, so the analyst is redirected away from it — and none
  // of the criteria / netting edit controls exist anywhere in their app.
  await page.goto("/template", DCL);
  await expect(page).not.toHaveURL(/\/template/);
  await expect(page.getByTestId("criteria-include")).toHaveCount(0);
  await expect(page.getByTestId("criteria-scope")).toHaveCount(0);
  await expect(page.getByTestId("netting-add")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save rule" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
});

test("admin tunes the extraction thresholds and they persist", async ({ page }) => {
  await loginAs(page, "admin");
  // The shipped configuration is the baseline this test compares against, so start from it
  // rather than from whatever a previous run left saved.
  await resetThresholds(page);

  // Every control is rendered from the backend's field descriptors, so the knob is present
  // without the screen knowing anything about mapping.
  const fuzzy = page.getByTestId("ex-fuzzy_accept");
  await expect(fuzzy).toBeVisible({ timeout: 15_000 });
  const shipped = await fuzzy.inputValue();

  // Save is inert until something actually changes.
  await expect(page.getByTestId("ex-save")).toBeDisabled();

  await fuzzy.fill("0.62");
  await expect(page.getByTestId("ex-save")).toBeEnabled();
  await page.getByTestId("ex-save").click();

  // It round-trips: a reload reads the value back from the server, so the pipeline really
  // holds it — not just this form.
  await page.reload(DCL);
  await expect(page.getByTestId("ex-fuzzy_accept")).toHaveValue("0.62", { timeout: 15_000 });

  // Out of range is refused before it can be sent, and says why.
  await page.getByTestId("ex-fuzzy_accept").fill("1.4");
  await expect(page.getByTestId("ex-save")).toBeDisabled();
  await expect(page.getByTestId("ex-message")).toContainText("at most 1");

  // Restore defaults puts the shipped configuration back — and leaves nothing behind for the
  // next run to inherit.
  await page.getByTestId("ex-reset").click();
  await expect(page.getByTestId("ex-fuzzy_accept")).toHaveValue(shipped, { timeout: 15_000 });
});

test("a saved threshold is still in force for a browser that never saw the edit", async ({
  page, browser,
}) => {
  // The reason these are persisted: an admin's change must not evaporate. A second browser
  // context shares nothing with the first except the server, so reading the saved value back
  // there is what proves it left the first tab.
  await loginAs(page, "admin");
  await page.goto("/settings", DCL);
  await expect(page.getByTestId("ex-mapping_margin")).toBeVisible({ timeout: 15_000 });
  const original = await page.getByTestId("ex-mapping_margin").inputValue();

  await page.getByTestId("ex-mapping_margin").fill("0.17");
  await page.getByTestId("ex-save").click();
  await expect(page.getByTestId("ex-save")).toBeDisabled({ timeout: 15_000 });

  const fresh = await browser.newContext();
  const other = await fresh.newPage();
  try {
    await loginAs(other, "admin");
    await other.goto("/settings", DCL);
    await expect(other.getByTestId("ex-mapping_margin")).toHaveValue("0.17", { timeout: 15_000 });
  } finally {
    await page.getByTestId("ex-reset").click();
    await expect(page.getByTestId("ex-mapping_margin")).toHaveValue(original, { timeout: 15_000 });
    await fresh.close();
  }
});

test("an analyst cannot reach the extraction thresholds at all", async ({ page }) => {
  // Settings is an admin-only SCREEN (see SCREENS_BY_ROLE): these knobs change how every
  // future extraction behaves, so an analyst gets neither the controls nor the screen.
  await loginAs(page, "analyst");
  await page.goto("/settings", DCL);

  await expect(page.getByTestId("ex-fuzzy_accept")).toHaveCount(0);
  await expect(page.getByTestId("ex-save")).toHaveCount(0);
  await expect(page.getByText("Fuzzy auto-accept")).toHaveCount(0);
});

test("the thresholds are still editable against a backend that omits the descriptors", async ({
  page,
}) => {
  // An older API returns the extraction VALUES without the field descriptions. Rendering from an
  // empty descriptor list produced a card with a Save button and no fields in it — visibly
  // broken, and silent about why. The controls are inferred from the values instead, and the
  // card says the ranges are not being checked locally.
  await page.route("**/api/v1/settings", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    delete body.extraction_fields;
    delete body.extraction_defaults;
    await route.fulfill({ response: res, json: body });
  });

  await loginAs(page, "admin");
  await page.goto("/settings", DCL);

  // Inferred from the value's own type: a number input for a threshold…
  const fuzzy = page.getByTestId("ex-fuzzy_accept");
  await expect(fuzzy).toBeVisible({ timeout: 15_000 });
  await expect(fuzzy).toHaveAttribute("type", "number");
  // …a toggle for the boolean, and a readable label rather than the raw key.
  await expect(page.getByTestId("ex-llm_mapping")).toBeVisible();
  await expect(page.getByText("Fuzzy accept")).toBeVisible();
  // And it is honest about the degraded mode.
  await expect(page.getByText(/did not describe these settings/i)).toBeVisible();

  // Still genuinely editable: the save round-trips through the real endpoint.
  await fuzzy.fill("0.58");
  await page.getByTestId("ex-save").click();
  await expect(page.getByTestId("ex-save")).toBeDisabled({ timeout: 15_000 });

  // Hand nothing to the next run: the save above is persisted.
  await page.unroute("**/api/v1/settings");
  await resetThresholds(page);
});

test("real extraction: prior-year links, an edit that sticks, KPIs and Additional items",
     async ({ page }) => {
  test.setTimeout(240_000);
  await loginAs(page, "analyst");
  await page.goto("/upload", DCL);
  // A two-column comparative, including a line printed for the PRIOR YEAR ONLY.
  await page.setInputFiles('input[type="file"]', "e2e/fixtures/comparative.pdf");
  await expect(page.getByTestId("doc-row").filter({ hasText: "comparative.pdf" }))
    .toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /Extract directly/ }).click();
  await expect(page.getByRole("heading", { name: "Extracted data" }))
    .toBeVisible({ timeout: 30_000 });

  await page.goto("/workspace", DCL);
  await expect(page.getByText("Trade receivables").first()).toBeVisible({ timeout: 20_000 });

  // --- last year's figure is its own hyperlink ---------------------------------------------
  // The title only exists when THAT period's value resolves to a source location, so clicking
  // it has to drive the viewer to the page it was printed on.
  const priorLink = page.locator('[title*="last year"]').first();
  await expect(priorLink).toBeVisible({ timeout: 15_000 });
  await priorLink.click();
  await expect(page.getByTestId("prov-highlight")).toBeVisible({ timeout: 15_000 });

  // --- the inspector describes the selected figure, along the bottom of the panel ------------
  await page.getByText("Trade receivables").first().click();
  const inspector = page.getByTestId("cell-inspector");
  await expect(inspector).toBeVisible({ timeout: 15_000 });
  // It sits BELOW the statement rows rather than beside them.
  const gridBox = await page.getByText("Trade receivables").first().boundingBox();
  const inspBox = await inspector.boundingBox();
  expect(inspBox!.y).toBeGreaterThan(gridBox!.y);

  // --- editing happens in the inspector, and the typed figure is the figure shown ------------
  await page.getByTestId("edit-value").click();
  const input = page.getByTestId("edit-v1");
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.fill("55555");
  // --- and an edit can say WHY ---------------------------------------------------------------
  await page.getByTestId("edit-comment").fill("Agreed with management");
  await page.getByTestId("edit-save").click();
  // Accepted → the editor closes. A refused save keeps it open and shows why, so this doubles as
  // the assertion that nothing was silently rejected.
  await expect(page.getByTestId("edit-v1")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByTestId("edit-error")).toHaveCount(0);
  await expect(page.getByText("55,555").first()).toBeVisible({ timeout: 15_000 });
  // The reason survives a reload and is shown against the figure it explains.
  await expect(page.getByTestId("inspector-comment")).toContainText("Agreed with management",
                                                                   { timeout: 15_000 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByText("Trade receivables").first().click();
  await expect(page.getByTestId("inspector-comment")).toContainText("Agreed with management",
                                                                   { timeout: 15_000 });

  await page.getByRole("button", { name: /Revert/ }).click();
  await expect(page.getByText("55,555")).toHaveCount(0, { timeout: 15_000 });

  // --- a subtotal shows what its components come to ------------------------------------------
  // Total assets is a calculated line: the grid marks it, and the inspector names the arithmetic
  // and lists the lines behind it.
  const calc = page.locator('[data-testid="origin-calculated"]').first();
  await expect(calc).toBeVisible({ timeout: 15_000 });
  await calc.click();
  await expect(page.getByTestId("inspector-origin-calculated")).toBeVisible();
  await expect(page.getByTestId("inspector-arithmetic")).toContainText(/\+|−|-/);

  // The rollup is a RENDERING of the figures, not an expression, so opening the editor must not
  // prefill the formula box with it: the server would evaluate what came back, and a computed
  // result outranks a typed value — the analyst's number would be silently replaced by the sum.
  await page.getByTestId("edit-value").click();
  await expect(page.getByTestId("edit-formula")).toHaveValue("");
  await page.getByRole("button", { name: "Cancel" }).click();

  // --- KPIs -------------------------------------------------------------------------------
  await page.getByTestId("seg-kpi").click();
  await expect(page.getByTestId("seg-kpi")).toHaveAttribute("data-on", "true");
  await expect(page.getByText("Liquidity").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Current ratio").first()).toBeVisible();
  // A ratio has no magnitude, so the presentation controls are absent rather than inert.
  await expect(page.getByText("Units", { exact: true })).toHaveCount(0);
  // Selecting one shows the extracted figures it was computed from.
  await page.getByText("Current ratio").first().click();
  await expect(page.getByText(/numerator:/).first()).toBeVisible({ timeout: 15_000 });

  // --- Additional items -------------------------------------------------------------------
  await page.getByTestId("seg-additional_items").click();
  await expect(page.getByTestId("seg-additional_items")).toHaveAttribute("data-on", "true");
  await expect(page.getByTestId("seg-kpi")).toHaveAttribute("data-on", "false");

  // Back to a statement: the magnitude selector returns, because these ARE amounts.
  await page.getByTestId("seg-balance_sheet").click();
  await expect(page.getByText("Units", { exact: true })).toBeVisible({ timeout: 15_000 });
});

test("an admin downloads the template as a workbook and publishes an edited version",
     async ({ page }) => {
  test.setTimeout(120_000);
  await loginAs(page, "admin");
  await page.goto("/template", DCL);
  await expect(page.getByTestId("template-authoring")).toBeVisible({ timeout: 20_000 });

  // Download the active template's workbook.
  const picker = page.getByTestId("template-picker");
  await expect(picker).toBeVisible();
  const before = await picker.locator("option").allTextContents();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("tpl-download-xlsx").click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  const path = await download.path();
  expect(path).toBeTruthy();

  // Upload it straight back: a NEW version of the same template, nothing overwritten.
  await page.getByTestId("tpl-xlsx-input").setInputFiles(path as string);
  const msg = page.getByTestId("tpl-auth-message");
  await expect(msg).toBeVisible({ timeout: 30_000 });
  await expect(msg).toContainText(/Published .* v\d+ — \d+ line items/);
  const after = await picker.locator("option").allTextContents();
  expect(after.length).toBe(before.length + 1);
});

test("an analyst gets no template authoring affordances", async ({ page }) => {
  await loginAs(page, "analyst");
  await page.goto("/template", DCL);
  // The screen itself is admin-only; whichever way it is refused, the controls must not exist.
  await expect(page.getByTestId("template-authoring")).toHaveCount(0);
  await expect(page.getByTestId("tpl-upload-xlsx")).toHaveCount(0);
});
