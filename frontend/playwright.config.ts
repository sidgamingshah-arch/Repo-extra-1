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
    launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
