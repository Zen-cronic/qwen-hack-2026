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

export const getPacks = () => fetch("/api/packs").then(j<{ packs: Pack[] }>);

// Backend stores paths under data/; the media route strips a leading data/.
export const mediaUrl = (p: string | null): string =>
  p ? `/api/media/${p.replace(/^data\//, "")}` : "";
