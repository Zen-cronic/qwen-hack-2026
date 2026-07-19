/** Derive a React Flow graph from a Project snapshot — the pipeline as a node graph.
 *
 * This is a pure function of the polled state: the same `ProjectState` the board and
 * stepper already read, reshaped into nodes + edges. It invents no new status — every
 * node's state is read off the shots/takes/results the server produced, so the canvas
 * stays a faithful view of the real run and updates on the ordinary 2.5s poll.
 *
 * The id scheme (script, stills, review, gen-{i}, check-{i}, assemble, episode) is
 * canonical and shared with the server-side plan expander, so a plan-drawn canvas and a
 * live-run canvas are the same nodes — live status merges straight in.
 */
import { type Edge, type Node, Position } from "@xyflow/react";
import { shortLabel } from "./vocabulary";
import type { Project, ShotState } from "./types";

export type NodeStatus =
  | "idle" | "active" | "done" | "failed" | "pass" | "fail" | "inconclusive";

export type NodeKind = "stage" | "review" | "shot" | "check" | "episode";

// React Flow requires node data to be an index-signed record; the typed fields below
// are what the custom node components read.
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
  [key: string]: unknown;
}

export type DNode = Node<DNodeData>;

// The linear order of the pipeline's project-level statuses, used only to ask
// "are we past stage X yet?" for the spine nodes. `failed` is off the line (rank -1).
const STATUS_ORDER = [
  "queued", "scripting", "tier0", "awaiting_review",
  "drafting", "verifying", "repairing", "promoting", "assembling", "done",
];
const rank = (s: string) => STATUS_ORDER.indexOf(s);

const latestTake = (shot: ShotState) =>
  shot.takes.length ? shot.takes[shot.takes.length - 1] : undefined;

// A clip was produced for this shot — mirrors ShotCard's thumb rule (first evidence
// frame of the latest take, else the pre-render still).
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

// Layout: a left-to-right spine (script > stills > review > assemble > episode) with a
// per-shot fan-out (gen > check) between review and assemble. Static coordinates — the
// topology is fixed, so there's no need for a layout engine.
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
        caption: t?.tier === "final" ? "premium take" : t ? "draft take" : "generate",
      },
    });
    nodes.push({
      id: `check-${i}`, type: "check", position: { x: col(4), y },
      data: {
        kind: "check", label: "Checks", status: cs, checks, shotIndex: i,
        caption: "Tier-A CV · VLM advisory",
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
  // An edge flows (animated + accent) when its source has completed and its target is
  // the active frontier — the eye follows work moving down the pipeline.
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

export { Position };
