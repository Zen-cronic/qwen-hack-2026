import { test } from "@playwright/test";

/** Regenerate the two README screenshots from the REAL-video fixtures runtime, so
 *  dailies-review.png / dailies-done.png show actual Wan footage + qwen-tts narration
 *  instead of synthetic slates.
 *
 *  Warm the cache first (one-time real spend):
 *      ~/.pyenv/versions/.qwen-hack/bin/python scripts/warm_fixtures.py
 *  Then:  npm --prefix web run shots:fixtures
 *
 *  Deliberately separate from the hermetic demo suite (e2e/demo-flow.spec.ts): this run has
 *  NO cold-cost assertions, because a warm fixtures cache replays every clip for free — the
 *  exact opposite of what the frontier-cost regression test needs. It only drives the flow
 *  far enough to capture the two frames.
 */
test("real-footage screenshots: review gate + certified episode", async ({ page }) => {
  await page.goto("/");
  // Fixtures ignores the premise (pinned shots) and compiles no custom checks; the default
  // pack (short_drama) is what its assertions target, so a bare create is all it needs.
  await page.getByTestId("create").click();

  // Review gate — real Tier-0 qwen-vl on the real still.
  await page.getByTestId("reviewbar").waitFor({ state: "visible", timeout: 180_000 });
  const firstThumb = page.getByTestId("shot").first().locator("img");
  await firstThumb.waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="shot"] img') as HTMLImageElement | null;
    return !!el && el.naturalWidth > 0;
  });
  await page.screenshot({ path: "../dailies-review.png", fullPage: true });

  // Approve → draft → Tier-A catches the real static kill-shot → repaired pan → certified cut.
  await page.getByTestId("approve").click();
  await page.getByTestId("finalcut").waitFor({ state: "visible", timeout: 600_000 });

  // Let the episode player paint a real frame before the shot (headless Chromium needs a seek).
  await page.waitForFunction(() => {
    const v = document.querySelector("video");
    return v !== null && v.readyState >= 2;
  });
  await page.evaluate(() => {
    const v = document.querySelector("video");
    if (v) v.currentTime = 0.1;
  });
  await page.waitForFunction(() => {
    const v = document.querySelector("video");
    return v !== null && !v.seeking && v.readyState >= 2;
  });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: "../dailies-done.png", fullPage: true });
});
