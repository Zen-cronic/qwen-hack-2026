import { expect, test } from "@playwright/test";

/** The whole user journey on the demo runtime: premise in, certified episode out.
 *
 * Set SCREENSHOTS=1 to also refresh the two README screenshots from this run
 * (review gate + finished dashboard) — kept behind a flag so CI runs stay clean.
 */
test("premise → review gate → certified episode, with live charts", async ({ page, request }) => {
  await page.goto("/");

  // New-run panel: prompt-first entry, sample premise prefilled. The custom check
  // is deliberately an ADVISORY one (title card): it exercises the plain-language →
  // vocabulary path without forcing a retake on every shot — "pan right" here would
  // make all three shots fail take 0 and flatten the frontier to one equal-cost dot,
  // hiding the planted kill-shot's 15s-vs-10s cost story the charts exist to tell.
  await expect(page.getByTestId("premise")).toBeVisible();
  await expect(page.getByTestId("premise")).not.toHaveValue("");
  await page.getByTestId("custom-checks").fill("a title card must be visible");
  await page.getByTestId("create").click();

  // Pipeline strip narrates each stage while the poll loop runs.
  await expect(page.getByTestId("pipeline")).toBeVisible();
  await expect(page.getByTestId("stage-caption")).toBeVisible();

  // The one human gate, with a tier-0 evidence summary instead of a blind unlock.
  await expect(page.getByTestId("reviewbar")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("tier0-summary")).toContainText("Tier-0");

  // The still thumbnails must actually LOAD, not just render an <img> tag: the
  // media route once 404'd every still under a non-default DATA_DIR and the only
  // visible symptom was broken-image icons a DOM assertion can't see.
  const firstThumb = page.getByTestId("shot").first().locator("img");
  await expect(firstThumb).toBeVisible();
  await expect
    .poll(() => firstThumb.evaluate((el) => (el as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  if (process.env.SCREENSHOTS) await page.screenshot({ path: "../dailies-review.png", fullPage: true });
  await page.getByTestId("approve").click();

  // Demo spine: draft → Tier-A catches the planted static-camera kill-shot →
  // repair issues a retake → the retake pans right and passes → assemble.
  await expect(page.getByTestId("finalcut")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("shot")).toHaveCount(3);
  await expect(page.getByTestId("shot-badge").filter({ hasText: "certified" }).first()).toBeVisible();

  // Dashboard: every chart carries data — no empty states on a finished run.
  const charts = page.getByTestId("charts");
  await expect(charts.getByText("No verifications yet.")).toHaveCount(0);
  await expect(charts.getByText("No shots yet.")).toHaveCount(0);
  await expect(charts.getByText("No takes yet.")).toHaveCount(0);
  expect(await charts.locator(".recharts-scatter-symbol").count()).toBeGreaterThan(0);

  // API-level regression for panel deduction #16: on a cold run the frontier must
  // carry real cost signal, not collapse to a single cost=0 dot.
  const id = new URL(page.url()).searchParams.get("p");
  expect(id).toBeTruthy();
  const proj = await (await request.get(`/api/projects/${id}`)).json();
  expect(proj.metrics.frontier.length).toBeGreaterThan(0);
  expect(proj.metrics.frontier.some((f: { cost_seconds: number }) => f.cost_seconds > 0)).toBeTruthy();

  // The kill-shot arc really happened: shot 1 needed more than one take and ended certified.
  expect(proj.shots[1].takes.length).toBeGreaterThan(1);
  expect(proj.shots[1].certified).toBeTruthy();

  if (process.env.SCREENSHOTS) {
    // Let the episode player paint a real frame — a black rectangle with a spinner
    // is not a deliverable screenshot of a "certified episode". Headless Chromium
    // doesn't render a frame until a seek completes, even at readyState >= 2.
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
    await page.waitForTimeout(500); // let Chrome's seek-spinner overlay fade out
    await page.screenshot({ path: "../dailies-done.png", fullPage: true });
  }

  // The report link is durable: reopening the deep link restores the finished run.
  await page.goto(`/?p=${id}`);
  await expect(page.getByTestId("finalcut")).toBeVisible({ timeout: 15_000 });
});

/** Warm re-verify — the judge-mode path. Same premise twice: the second run is served
 * entirely from the content-addressed cache, bills zero video-seconds, and the frontier
 * must still read (production cost per shot, replay note visible) instead of collapsing
 * every shot to a single dot at cost=0 — the original panel deduction #16. */
test("a fully cached re-run keeps the frontier readable and the bill at zero", async ({ page, request }) => {
  const run = async () => {
    await page.goto("/");
    await page.getByTestId("create").click();
    await expect(page.getByTestId("reviewbar")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("approve").click();
    await expect(page.getByTestId("finalcut")).toBeVisible({ timeout: 120_000 });
    return new URL(page.url()).searchParams.get("p");
  };

  await run();               // warms the cache (or is already warm — either is fine)
  const id = await run();    // definitely warm: every clip is a replay

  const proj = await (await request.get(`/api/projects/${id}`)).json();
  const frontier: { cost_seconds: number; production_seconds: number; replayed: boolean }[] =
    proj.metrics.frontier;
  expect(frontier.length).toBeGreaterThan(0);
  // This run billed nothing — the wallet's judge-mode "$0.00" story...
  expect(frontier.every((f) => f.cost_seconds === 0)).toBeTruthy();
  expect(proj.wallet.video_seconds).toBe(0);
  // ...while the chart still shows what each shot cost to produce, replay flagged.
  expect(frontier.every((f) => f.production_seconds > 0 && f.replayed)).toBeTruthy();
  await expect(page.getByTestId("frontier-replay-note")).toBeVisible();
});
