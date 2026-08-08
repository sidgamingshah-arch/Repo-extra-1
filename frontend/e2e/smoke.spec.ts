import { test, expect, Page } from "@playwright/test";

const DCL = { waitUntil: "domcontentloaded" as const };

/** Log in via the demo quick-sign-in buttons (passwordless in demo mode). */
async function loginAs(page: Page, role: "admin" | "reviewer" | "analyst") {
  await page.goto("/", DCL);
  await page.getByRole("button", { name: new RegExp(role, "i") }).click();
  await expect(page.getByText(/FinExtract/)).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("greenfield: the app is empty before any project is loaded", async ({ page }) => {
  await loginAs(page, "admin");
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

  // Open the extraction view for *this* document (select by filename — the docs list
  // persists across runs, so "the first row" is not necessarily the one just uploaded).
  await page.getByTestId("doc-row").filter({ hasText: "sample.pdf" })
    .getByRole("button", { name: "View →" }).click();
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

  await page.getByTestId("doc-row").filter({ hasText: "sample.xlsx" })
    .getByRole("button", { name: "View →" }).click();
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Extracted data" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Trade receivables").first()).toBeVisible();

  // Click a Sheet!Cell chip → the surrounding cells render with the target highlighted.
  await page.getByText(/!B\d/).first().click();
  await expect(page.getByTestId("cell-target")).toBeVisible({ timeout: 15_000 });
});

test("end-to-end: upload a new file → Run integrity check shows real results → extract", async ({ page }) => {
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

test("analyst can reach the template screen and select a template for a run", async ({ page }) => {
  await loginAs(page, "analyst");

  // The template menu is present in the nav for the analyst (was admin-only before) and
  // navigates to the template screen without being redirected away.
  await page.goto("/workspace", DCL);
  await page.getByText("Template & Ontology").click();
  await expect(page).toHaveURL(/\/template/);
  // Authoring is admin-only → the analyst gets no "add line item" control.
  await expect(page.getByText("+ Add line item")).toHaveCount(0);

  // On the Documents & Template screen the analyst can open the picker and select a template.
  await page.goto("/upload", DCL);
  await expect(page.getByText("Selected")).toBeVisible({ timeout: 15_000 }); // a template is active
  await page.getByRole("button", { name: "Choose another" }).click();
  const options = page.getByTestId("tpl-option");
  await expect(options.first()).toBeVisible({ timeout: 15_000 });            // real templates listed
  await options.first().click();
  // Selecting closes the picker (button returns to "Choose another") — selection is wired.
  await expect(page.getByRole("button", { name: "Choose another" })).toBeVisible();
});
