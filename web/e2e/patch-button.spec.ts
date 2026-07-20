import { test, expect } from "@playwright/test";
import type { AssertionResult, Project, ShotState } from "../src/types";

/** The graph's per-node re-render button, on a shot that actually failed.
 *
 *  Both the demo and fixture runs end fully certified — the repair loop closes every
 *  blocking failure — so this control never appears in either suite and shipped
 *  unlooked-at. The payload is typed as `Project`, so the compiler holds it to the same
 *  shape `GET /api/projects/{pid}` returns; only the transport is stubbed, while the
 *  derive path (graph.ts) and the button (nodes.tsx) are the real ones.
 *
 *  It is written here rather than captured from a live run on purpose: a dumped payload
 *  carries local filesystem paths and run ids, which do not belong in the repo.
 */
const failing = (window: [number, number]): AssertionResult => ({
  type: "camera_motion", tier: "tier_a", advisory: false, status: "fail",
  detail: "camera static, |v|=0.005 (want right)",
  measured: { fail_window_s: window }, evidence: [], params: { direction: "right" },
});

// The pack defaults every shot carries, so the check nodes render the chip set a real run
// shows rather than a bare node.
const passing = (type: string): AssertionResult => ({
  type, tier: "tier_a", advisory: false, status: "pass", detail: "measured",
  measured: {}, evidence: [], params: {},
});
const BASE = ["duration_between", "brightness_range", "flicker_below", "scene_cuts"]
  .map(passing);

const shot = (index: number, certified: boolean, extra: AssertionResult[]): ShotState => ({
  spec: { index, prompt: `shot ${index}`, subject: null, assertions: [] },
  status: certified ? "certified" : "failed",
  still_path: null, tier0_results: [],
  takes: [{
    take_no: 0, tier: "draft", model: "wan2.1-t2v-turbo", prompt: `shot ${index}`,
    status: "done", video_path: `shot${index}.mp4`, results: [...BASE, ...extra],
    passed: certified,
  }],
  certified, final_path: certified ? `shot${index}.mp4` : null,
});

// Shot 1 is static for its whole duration, so Tier-A localises the failure to [0, 4.88] —
// the shape the planted kill-shot actually produces.
const project: Project = {
  id: "failshot", premise: "a lonely lighthouse keeper", pack: "short_drama", max_shots: 3,
  custom_checks: [], cast: {}, status: "done",
  shots: [shot(0, true, []), shot(1, false, [failing([0, 4.88])]), shot(2, true, [])],
  wallet: {
    draft_clips: 3, final_clips: 2, patch_clips: 0, images: 3,
    tokens_in: 270, tokens_out: 90, video_seconds: 25, est_usd: 4.56,
  },
  episode_path: null, error: null,
  metrics: {
    summary: { shots_total: 3, certified: 2, failed: 1 },
    heatmap: {}, frontier: [], convergence: [],
    repair: { retakes_total: 0, shots_repaired: 0, repair_successes: 0 },
    cost_per_passing_second: null, transfer_rate: null,
  },
};

test("a failed shot offers a re-render on its check node", async ({ page }) => {
  await page.route("**/api/projects/*", (route) => route.fulfill({ json: project }));
  await page.goto("/?p=failshot");

  await page.getByTestId("graph").waitFor({ state: "visible" });

  // Exactly one shot failed, so exactly one node offers the re-render: the control is
  // gated on a blocking Tier-A failure, not merely on "this shot is not certified".
  const patch = page.getByTestId("node-patch");
  await expect(patch).toHaveCount(1);
  await expect(patch).toBeVisible();

  // This window opens at t=0, so there is no frame to anchor to and the server will
  // re-roll the whole clip. The label must not name a second it will not honour.
  await expect(patch).toHaveText("⟲ re-render this shot");

  if (process.env.SCREENSHOTS) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    // test-results/ is gitignored: this is a local eyeball, not a repo artifact.
    await page.getByTestId("graph").screenshot({ path: "test-results/patch-button.png" });
  }
});

test("a mid-clip failure names the second it will anchor at", async ({ page }) => {
  const midClip: Project = {
    ...project,
    shots: [shot(0, true, []), shot(1, false, [failing([1.5, 3.0])]), shot(2, true, [])],
  };
  await page.route("**/api/projects/*", (route) => route.fulfill({ json: midClip }));
  await page.goto("/?p=failshot");

  await page.getByTestId("graph").waitFor({ state: "visible" });
  // 1.5 - ANCHOR_LEAD_S, the same arithmetic server/patch.py does — the label is a
  // promise about where the re-render starts, not an approximation.
  await expect(page.getByTestId("node-patch")).toHaveText("⟲ re-render from 1.3s");
});
