import type { Pack, Project } from "./types";

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

/** Re-render one shot from its last good frame and re-verify it. Slow (a real
 *  generation), so callers should await it rather than relying on the poll loop. */
export const patchShot = (id: string, shotIndex: number) =>
  fetch(`/api/projects/${id}/shots/${shotIndex}/patch`, { method: "POST" })
    .then(j<{ ok: boolean; reason: string; anchor_s: number | null; certified: boolean }>);

export const getPacks = () => fetch("/api/packs").then(j<{ packs: Pack[] }>);

// The stored path IS the contract: pass it verbatim and let the media route
// resolve it against its own DATA_ROOT guard. Any client-side prefix surgery
// here has to guess the server's DATA_DIR — and guesses wrong the moment it
// isn't literally "data" (e2e runs use data/e2e; scratch runs are absolute).
export const mediaUrl = (p: string | null): string =>
  p ? `/api/media/${p}` : "";
