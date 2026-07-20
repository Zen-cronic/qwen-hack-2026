import { test } from "@playwright/test";

/** Regenerates the README screenshots from the real-video fixtures runtime. Warm the cache
 *  first (scripts/warm_fixtures.py), then: npm --prefix web run shots:fixtures */
test("real-footage screenshots: review gate + certified episode", async ({ page }) => {
  await page.goto("/");
  // Fixtures pins its shots and targets the default pack, so a bare create is all it needs.
  await page.getByTestId("create").click();

  // Review gate — real Tier-0 qwen-vl on the real still.
  await page.getByTestId("reviewbar").waitFor({ state: "visible", timeout: 180_000 });
  const firstThumb = page.getByTestId("shot").first().locator("img");
  await firstThumb.waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="shot"] img') as HTMLImageElement | null;
    return !!el && el.naturalWidth > 0;
  });
  // Reset scroll so the sticky AppBar composites at the top of the full-page capture.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
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
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await page.screenshot({ path: "../dailies-done.png", fullPage: true });
});
