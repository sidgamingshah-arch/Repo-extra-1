import { defineConfig } from "@playwright/test";

// Frontend smoke regression. Boots the FastAPI backend + Vite dev server (which proxies
// /api → backend) and drives the real UI in the preinstalled Chromium. Serial + single
// worker because the "load sample" flow toggles process-wide backend state.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    headless: true,
    navigationTimeout: 20_000,
    // Kept on for diagnosis: the suite failed at a DIFFERENT test on two consecutive runs of one
    // tree, both times waiting for a screen to settle, and the page snapshot alone did not say
    // why. A trace carries the network timeline and the console, which is what distinguishes "the
    // server was slow" from "the dev server reloaded the page under us".
    trace: "retain-on-failure",
    launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      // NEVER adopt a server that is already listening. It reads as a convenience, but it makes
      // the suite's result depend on machine state: a server left running from an earlier run
      // serves the code IT was started with, so the suite silently tests something other than the
      // working tree. That is not hypothetical — it produced a 500 in the extraction view that
      // could not be reproduced in-process, over HTTP, or against a fresh server, and it is why
      // two agents reported 19 passed and 1 failed for the same commit: they were talking to
      // different servers. Starting our own costs a few seconds; if the port is occupied,
      // Playwright now fails loudly instead of testing the wrong thing.
      reuseExistingServer: false,
      timeout: 120_000,
      // Force deterministic mapping so the (network-blocked) LLM isn't attempted during
      // e2e — keeps extraction fast and offline; alias-tier mapping still populates.
      env: { FINEX_EXTRACTION__LLM_MAPPING: "false" },
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      // Reuse is fine HERE, and the asymmetry with the backend above is the point: vite reads the
      // source from disk on request and hot-replaces it, so an already-running dev server is
      // serving the working tree. Uvicorn is not — it imports the Python once at start-up and
      // holds it — which is why only that one refuses to be adopted.
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
