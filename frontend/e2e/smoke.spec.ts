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
  await expect(page.getByText("sample.pdf")).toBeVisible({ timeout: 15_000 });

  // Open the real extraction view for the uploaded document.
  await page.getByRole("button", { name: "View →" }).first().click();
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Extracted data" })).toBeVisible({ timeout: 15_000 });
  // Real extracted line item + click-to-source provenance from the native PDF.
  await expect(page.getByText("Trade receivables").first()).toBeVisible();
  await expect(page.getByText(/^p\.1/).first()).toBeVisible();
});
