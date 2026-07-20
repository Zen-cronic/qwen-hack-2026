/** Derive a React Flow graph from a Project snapshot — pure, from the polled state.
 *  Node ids (script/stills/review/gen-{i}/check-{i}/assemble/episode) must match the server's plan expander. */
import { type Edge, type Node, Position } from "@xyflow/react";
import { shortLabel } from "./vocabulary";
import type { AssertionResult, PipelinePlan, Project, ShotState } from "./types";

export type NodeStatus =
  | "idle" | "active" | "done" | "failed" | "pass" | "fail" | "inconclusive";

export type NodeKind = "stage" | "review" | "shot" | "check" | "episode";

// React Flow requires node data to be an index-signed record.
export interface DNodeData {
  kind: NodeKind;
  label: string;
  status: NodeStatus;
  caption?: string;
  model?: string;
  thumb?: string | null;              // raw media path — the node mediaUrl()s it
  checks?: { label: string; status: string }[];
  shotIndex?: number;
  episodePath?: string | null;
  enterDelay?: number;                // ms; set only for the staggered plan reveal
  // Patch affordance — derived here, wired to a handler at the PipelineGraph boundary.
  patchable?: boolean;
  anchorS?: number;                   // the second the re-render will anchor at
  failLabel?: string;                 // the blocking check that isn't true yet
  onPatch?: (shotIndex: number) => void | Promise<void>;
  [key: string]: unknown;
}

export type DNode = Node<DNodeData>;

// Project-level status order, for "are we past stage X yet?". `failed` is off it (-1).
const STATUS_ORDER = [
  "queued", "scripting", "tier0", "awaiting_review",
  "drafting", "verifying", "repairing", "promoting", "assembling", "done",
];
const rank = (s: string) => STATUS_ORDER.indexOf(s);

const latestTake = (shot: ShotState) =>
  shot.takes.length ? shot.takes[shot.takes.length - 1] : undefined;

// Must match ANCHOR_LEAD_S in server/patch.py and in components.tsx (ShotCard's gate).
const ANCHOR_LEAD_S = 0.2;

function failWindow(r: AssertionResult): [number, number] | null {
  const raw = r.measured?.fail_window_s;
  if (!Array.isArray(raw) || raw.length !== 2) return null;
  const [lo, hi] = raw;
  return typeof lo === "number" && typeof hi === "number" ? [lo, hi] : null;
}

// The blocking failure a patch targets: non-advisory, failed, localizable, latest take.
function patchTarget(shot: ShotState): AssertionResult | undefined {
  return latestTake(shot)?.results.find(
    (r) => !r.advisory && r.status === "fail" && failWindow(r),
  );
}

// Mirrors ShotCard's thumb rule: first evidence frame of the latest take, else the still.
function shotThumb(shot: ShotState): string | null {
  const t = latestTake(shot);
  return t?.results.find((r) => r.evidence.length)?.evidence[0] ?? shot.still_path;
}

function genStatus(shot: ShotState): NodeStatus {
  const t = latestTake(shot);
  if (t?.video_path || (shot.certified && shot.final_path)) return "done";
  if (["drafting", "repairing", "promoting"].includes(shot.status)) return "active";
  if (t && (t.status === "generating" || t.status === "queued")) return "active";
  if (shot.status === "failed") return "failed";
  return "idle";
}

function checkState(shot: ShotState): { status: NodeStatus; checks: DNodeData["checks"] } {
  const t = latestTake(shot);
  if (!t || !t.video_path) return { status: "idle", checks: [] };
  // Measured (non-advisory) checks first — they are the ones that gate promotion.
  const ordered = [...t.results].sort((a, b) => Number(a.advisory) - Number(b.advisory));
  const checks = ordered.map((r) => ({ label: shortLabel(r.type), status: r.status }));
  const status: NodeStatus =
    t.passed === true ? "pass" : t.passed === false ? "fail" : "active";
  return { status, checks };
}

// Static layout: a left-to-right spine with a per-shot fan-out between review and assemble.
const COL = 210;
const ROW = 148;
const col = (i: number) => i * COL;

export function deriveNodes(project: Project): DNode[] {
  const shots = project.shots;
  const n = shots.length || project.max_shots || 3;
  const status = project.status;
  const now = rank(status);
  const centerY = ((n - 1) * ROW) / 2;

  const nodes: DNode[] = [];

  // Spine: script
  const scriptStatus: NodeStatus = shots.length
    ? "done"
    : ["queued", "scripting"].includes(status) ? "active" : "idle";
  nodes.push({
    id: "script", type: "stage", position: { x: col(0), y: centerY },
    data: {
      kind: "stage", label: "Script", status: scriptStatus,
      caption: shots.length ? `${shots.length} shots` : "shot list · qwen-plus",
    },
  });

  // Spine: stills (Tier-0 pre-screen)
  const allStills = shots.length > 0 && shots.every((s) => s.tier0_results.length > 0 || s.still_path);
  const stillsStatus: NodeStatus =
    status === "tier0" ? "active"
      : allStills && now !== -1 && now >= rank("tier0") ? "done"
        : allStills ? "done" : "idle";
  nodes.push({
    id: "stills", type: "stage", position: { x: col(1), y: centerY },
    data: {
      kind: "stage", label: "Stills", status: stillsStatus,
      caption: "pre-screen · 1/25th cost",
    },
  });

  // Spine: review — the one human gate
  const reviewStatus: NodeStatus =
    status === "awaiting_review" ? "active"
      : now > rank("awaiting_review") ? "done"
        : shots.some((s) => s.takes.length) ? "done" : "idle";
  nodes.push({
    id: "review", type: "review", position: { x: col(2), y: centerY },
    data: {
      kind: "review", label: "Review", status: reviewStatus,
      caption: reviewStatus === "active" ? "waiting for you" : "human gate",
    },
  });

  // Per-shot fan-out: gen > check
  for (let i = 0; i < n; i++) {
    const shot = shots[i];
    const y = i * ROW;
    const g: NodeStatus = shot ? genStatus(shot) : "idle";
    const { status: cs, checks } = shot ? checkState(shot) : { status: "idle" as NodeStatus, checks: [] };
    const t = shot ? latestTake(shot) : undefined;
    nodes.push({
      id: `gen-${i}`, type: "shot", position: { x: col(3), y },
      data: {
        kind: "shot", label: `Shot ${i}`, status: g, shotIndex: i,
        model: t?.model, thumb: shot ? shotThumb(shot) : null,
        // "final", not "premium": promotion is a frame-anchored i2v continuation.
        caption: t?.tier === "final" ? "final take" : t ? "draft take" : "generate",
      },
    });
    const target = shot ? patchTarget(shot) : undefined;
    nodes.push({
      id: `check-${i}`, type: "check", position: { x: col(4), y },
      data: {
        kind: "check", label: "Checks", status: cs, checks, shotIndex: i,
        caption: "Tier-A CV · VLM advisory",
        patchable: !!target,
        anchorS: target ? Math.max(0, failWindow(target)![0] - ANCHOR_LEAD_S) : undefined,
        failLabel: target ? shortLabel(target.type) : undefined,
      },
    });
  }

  // Spine: assemble
  const assembleStatus: NodeStatus =
    project.episode_path || status === "done" ? "done"
      : status === "assembling" ? "active" : "idle";
  nodes.push({
    id: "assemble", type: "stage", position: { x: col(5), y: centerY },
    data: { kind: "stage", label: "Assemble", status: assembleStatus, caption: "ffmpeg cut" },
  });

  // Spine: episode
  const episodeStatus: NodeStatus =
    project.episode_path ? "done" : status === "assembling" ? "active" : "idle";
  nodes.push({
    id: "episode", type: "episode", position: { x: col(6), y: centerY },
    data: {
      kind: "episode", label: "Episode", status: episodeStatus,
      episodePath: project.episode_path,
      caption: project.episode_path
        ? `${project.metrics.summary.certified}/${project.metrics.summary.shots_total} certified`
        : "certified cut",
    },
  });

  return nodes;
}

export function deriveEdges(project: Project): Edge[] {
  const n = project.shots.length || project.max_shots || 3;
  const byId = new Map(deriveNodes(project).map((nd) => [nd.id, nd.data.status]));
  // An edge flows when its source has completed and its target is the active frontier.
  const flows = (src: string, dst: string) => {
    const s = byId.get(src);
    const d = byId.get(dst);
    const srcDone = s === "done" || s === "pass";
    return srcDone && (d === "active");
  };
  const edge = (source: string, target: string): Edge => ({
    id: `${source}->${target}`, source, target,
    animated: flows(source, target),
    style: { stroke: flows(source, target) ? "#4a9eff" : "#2a3240", strokeWidth: 1.5 },
  });

  const edges: Edge[] = [edge("script", "stills"), edge("stills", "review")];
  for (let i = 0; i < n; i++) {
    edges.push(edge("review", `gen-${i}`));
    edges.push(edge(`gen-${i}`, `check-${i}`));
    edges.push(edge(`check-${i}`, "assemble"));
  }
  edges.push(edge("assemble", "episode"));
  return edges;
}

// A Project-shaped stub so a plan renders through the same derive path as a live run.
// status "planned" is off the status line, so every node reads idle.
export function planStubProject(plan: PipelinePlan): Project {
  return {
    id: "", premise: plan.premise, pack: plan.pack, max_shots: plan.max_shots,
    // Casting happens at scripting, which a plan has not reached — so no cast yet.
    custom_checks: plan.custom_checks, cast: {}, status: "planned", shots: [],
    wallet: {
      draft_clips: 0, final_clips: 0, patch_clips: 0, images: 0,
      tokens_in: 0, tokens_out: 0, video_seconds: 0, est_usd: 0,
    },
    episode_path: null, error: null,
    metrics: {
      summary: { shots_total: 0, certified: 0, failed: 0 },
      heatmap: {}, frontier: [], convergence: [],
      repair: { retakes_total: 0, shots_repaired: 0, repair_successes: 0 },
      cost_per_passing_second: null, transfer_rate: null,
    },
  };
}

export { Position };
