import { expect, test } from "@playwright/test";

/** The whole user journey on the demo runtime: premise in, certified episode out.
 *  SCREENSHOTS=1 also refreshes the two README screenshots from this run. */
test("premise → review gate → certified episode, with live charts", async ({ page, request }) => {
  await page.goto("/");

  // The custom check must stay ADVISORY (title card): "pan right" would fail every shot's
  // take 0 and flatten the frontier to one equal-cost dot.
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

  // Thumbnails must actually LOAD, not just render an <img>: a broken media route only
  // shows up as broken-image icons, which a DOM assertion can't see.
  const firstThumb = page.getByTestId("shot").first().locator("img");
  await expect(firstThumb).toBeVisible();
  await expect
    .poll(() => firstThumb.evaluate((el) => (el as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  if (process.env.SCREENSHOTS) await page.screenshot({ path: "../dailies-review.png", fullPage: true });
  await page.getByTestId("approve").click();

  // Demo spine: draft → Tier-A catches the planted kill-shot → retake passes → assemble.
  await expect(page.getByTestId("finalcut")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("shot")).toHaveCount(3);
  await expect(page.getByTestId("shot-badge").filter({ hasText: "certified" }).first()).toBeVisible();

  // Dashboard: every chart carries data — no empty states on a finished run.
  const charts = page.getByTestId("charts");
  await expect(charts.getByText("No verifications yet.")).toHaveCount(0);
  await expect(charts.getByText("No shots yet.")).toHaveCount(0);
  await expect(charts.getByText("No takes yet.")).toHaveCount(0);
  expect(await charts.locator(".recharts-scatter-symbol").count()).toBeGreaterThan(0);

  // Regression: on a cold run the frontier must carry real cost signal, not collapse to 0.
  const id = new URL(page.url()).searchParams.get("p");
  expect(id).toBeTruthy();
  const proj = await (await request.get(`/api/projects/${id}`)).json();
  expect(proj.metrics.frontier.length).toBeGreaterThan(0);
  expect(proj.metrics.frontier.some((f: { cost_seconds: number }) => f.cost_seconds > 0)).toBeTruthy();

  // The kill-shot arc really happened: shot 1 needed more than one take and ended certified.
  expect(proj.shots[1].takes.length).toBeGreaterThan(1);
  expect(proj.shots[1].certified).toBeTruthy();

  if (process.env.SCREENSHOTS) {
    // Headless Chromium won't paint a video frame until a seek completes, even at
    // readyState >= 2 — without this the screenshot is a black rectangle.
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
    await page.waitForTimeout(1000); // let Chrome's seek-spinner overlay fade out fully
    await page.screenshot({ path: "../dailies-done.png", fullPage: true });
  }

  // The report link is durable: reopening the deep link restores the finished run.
  await page.goto(`/?p=${id}`);
  await expect(page.getByTestId("finalcut")).toBeVisible({ timeout: 15_000 });
});

/** Warm re-verify: the second run replays the cache, bills zero video-seconds, and the
 *  frontier must still read instead of collapsing every shot to one dot at cost=0. */
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
