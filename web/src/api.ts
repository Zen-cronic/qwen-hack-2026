import type { Pack, PlanResponse, Project } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

const JSON_POST = { method: "POST", headers: { "Content-Type": "application/json" } };

export const createProject = (premise: string, pack: string, max_shots: number, custom_checks: string[] = []) =>
  fetch("/api/projects", { ...JSON_POST, body: JSON.stringify({ premise, pack, max_shots, custom_checks }) })
    .then(j<{ id: string }>);

export const getProject = (id: string) => fetch(`/api/projects/${id}`).then(j<Project>);

export const review = (id: string) =>
  fetch(`/api/projects/${id}/review`, { method: "POST" }).then(j<{ ok: boolean }>);

export const sendVerdict = (id: string, shot_index: number, assertion_type: string, verdict: string) =>
  fetch(`/api/projects/${id}/verdict`, { ...JSON_POST, body: JSON.stringify({ shot_index, assertion_type, verdict }) })
    .then(j<{ ok: boolean }>);

/** Re-render one shot from its last good frame. Slow — await it, don't rely on the poll. */
export const patchShot = (id: string, shotIndex: number) =>
  fetch(`/api/projects/${id}/shots/${shotIndex}/patch`, { method: "POST" })
    .then(j<{ ok: boolean; reason: string; anchor_s: number | null; certified: boolean }>);

export const getPacks = () => fetch("/api/packs").then(j<{ packs: Pack[] }>);

/** Ask the Qwen agent to author a pipeline — returns the expanded plan and the transcript. */
export const planPipeline = (message: string) =>
  fetch("/api/agent/plan", { ...JSON_POST, body: JSON.stringify({ message }) })
    .then(j<PlanResponse>);

// Pass the stored path verbatim — the media route resolves it against DATA_ROOT. Any
// client-side prefix surgery would have to guess DATA_DIR (e2e uses data/e2e).
export const mediaUrl = (p: string | null): string =>
  p ? `/api/media/${p}` : "";
