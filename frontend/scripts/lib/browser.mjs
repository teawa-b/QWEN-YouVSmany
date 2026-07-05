/**
 * Shared headless-browser launcher for the capture/QA/package scripts.
 *
 * Launch order:
 *   1. YVM_BROWSER_PATH env var (explicit Chromium/Chrome executable) —
 *      lets the scripts run in containers/CI with a system browser when the
 *      pinned Playwright browser build is not downloaded.
 *   2. Edge channel (matches the original Windows-first development setup).
 *   3. Playwright's own managed Chromium.
 */
export async function launchBrowser(playwright, { headless = true } = {}) {
  const attempts = [];
  if (process.env.YVM_BROWSER_PATH) {
    attempts.push({ executablePath: process.env.YVM_BROWSER_PATH, headless });
  }
  attempts.push({ channel: "msedge", headless }, { headless });

  let lastError;
  for (const opts of attempts) {
    try {
      return await playwright.chromium.launch(opts);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}
