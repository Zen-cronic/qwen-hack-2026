import { expect, test } from "@playwright/test";

/** The whole user journey on the demo runtime: premise in, certified episode out.
 *
 * Set SCREENSHOTS=1 to also refresh the two README screenshots from this run
 * (review gate + finished dashboard) — kept behind a flag so CI runs stay clean.
 */
test("premise → review gate → certified episode, with live charts", async ({ page, request }) => {
  await page.goto("/");

  // New-run panel: prompt-first entry, sample premise prefilled.
  await expect(page.getByTestId("premise")).toBeVisible();
  await expect(page.getByTestId("premise")).not.toHaveValue("");
  await page.getByTestId("custom-checks").fill("the camera should pan right");
  await page.getByTestId("create").click();

  // Pipeline strip narrates each stage while the poll loop runs.
  await expect(page.getByTestId("pipeline")).toBeVisible();
  await expect(page.getByTestId("stage-caption")).toBeVisible();

  // The one human gate, with a tier-0 evidence summary instead of a blind unlock.
  await expect(page.getByTestId("reviewbar")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("tier0-summary")).toContainText("Tier-0");
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

  if (process.env.SCREENSHOTS) await page.screenshot({ path: "../dailies-done.png", fullPage: true });

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
