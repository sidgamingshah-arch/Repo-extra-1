/**
 * Delete and recreate the suite's throwaway database + object store directory.
 *
 * Run as the first half of the backend `webServer.command` (see playwright.config.ts), so the store
 * is emptied by the very process that is about to serve out of it — exactly once per run, and at the
 * one moment nothing is holding the file open. The two places this could otherwise live are both
 * wrong, and both were tried:
 *
 *   * `globalSetup` runs AFTER the webServers, because Playwright implements `webServer` as a plugin
 *     and plugin setup precedes global setup. A wipe there deletes a database the backend has
 *     already opened and seeded.
 *   * the config's own module scope runs TWICE — once in the runner and once in every worker
 *     process, i.e. after the server is up. Measured: "CONFIG LOADED in pid 3109 worker=undefined"
 *     then "in pid 3132 worker=0". A wipe there deletes the database out from under the run.
 *
 * The directory arrives in E2E_SCRATCH_DIR rather than in argv, so no path is ever interpolated into
 * the shell string Playwright runs: `env` is handed to the process, while `command` goes through
 * `/bin/sh -c`, where `$`, a backtick and a backslash stay live inside double quotes.
 */
import { mkdirSync, rmSync } from "node:fs";
import { basename, isAbsolute } from "node:path";

const dir = process.env.E2E_SCRATCH_DIR;

// This script's whole body is a recursive delete, so it refuses anything that is not recognisably
// the suite's own scratch directory rather than trusting its caller. A typo in the config must not
// be able to remove a source tree.
if (!dir || !isAbsolute(dir) || basename(dir) !== ".scratch") {
  console.error(
    `reset-scratch: refusing E2E_SCRATCH_DIR=${JSON.stringify(dir ?? null)} — expected an absolute `
    + 'path ending in ".scratch"',
  );
  process.exit(1);
}

rmSync(dir, { recursive: true, force: true });
// The object store root is created by the adapter on first write, but the DB's parent directory is
// not created by SQLite: an absent directory is "unable to open database file" at startup.
mkdirSync(dir, { recursive: true });
// stderr, not stdout: Playwright's webServer pipes a child's stderr into the run output and IGNORES
// its stdout, which is why uvicorn's banner is in the log and a console.log here was not. The one
// line that says "this run started from an empty store" has to be readable in the run's own output.
console.error(`reset-scratch: ${dir} is empty`);
