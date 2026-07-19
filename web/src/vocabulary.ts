/** Plain-language names for the closed assertion vocabulary and the pipeline stages.
 *
 * The machine names ARE the product — a closed DSL is the thing rivals don't have, and
 * the hero shows it off deliberately. But `subject_present` on a result row tells a
 * showrunner nothing, and worse, it hides the part they care about: WHICH subject. So
 * the rule here is translate, never replace — every surface shows the sentence a person
 * reads and keeps the machine token beside it, in mono, as the receipt.
 *
 * Phrasing follows the interface's voice: plain verbs, sentence case, describing what
 * must be true of the footage rather than how the check is implemented.
 */
import type { AssertionResult } from "./types";

/** Subjects arrive from the script agent either phrased ("the lighthouse keeper") or
 *  slugged ("ginger_street_cat"). Normalize both to something readable mid-sentence. */
export function humanizeSubject(raw: unknown): string {
  const s = typeof raw === "string" ? raw.trim() : "";
  if (!s) return "the subject";
  return s.replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

const sentence = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

const num = (v: number) => String(Number.isInteger(v) ? v : Number(v.toFixed(1)));

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Param-free phrasing, for results recorded before `params` rode along on the wire (or
 *  by any producer that omits them). Still a sentence a person can read — an earlier
 *  version interpolated missing values and rendered "Runs ?–? seconds", which is worse
 *  than the machine name it replaced. Degrade to vaguer, never to broken. */
const GENERIC: Record<string, string> = {
  duration_between: "Runs the expected length",
  scene_cuts: "No more cuts than allowed",
  camera_motion: "Camera moves as specified",
  subject_present: "The subject is in frame",
  identity_consistent: "The subject looks the same throughout",
  action_completed: "The action completes on screen",
};

/** Short noun phrase — for chart axes and anywhere space is the constraint. */
export const SHORT_LABEL: Record<string, string> = {
  duration_between: "Duration",
  brightness_range: "Exposure",
  flicker_below: "Flicker",
  scene_cuts: "Cuts",
  camera_motion: "Camera",
  palette_deltae: "Palette",
  subject_present: "Subject in frame",
  identity_consistent: "Same subject throughout",
  action_completed: "Action completes",
  title_card_present: "Title card",
};

export const shortLabel = (type: string) => SHORT_LABEL[type] ?? type.replace(/_/g, " ");

/** The full sentence for a result row: what this check requires of the footage.
 *  Params are folded in, because "at most 1 cut" and "no cuts at all" are different
 *  promises and the type name alone cannot tell them apart. */
export function checkLabel(r: Pick<AssertionResult, "type" | "params">): string {
  const p = (r.params ?? {}) as Record<string, unknown>;
  const generic = GENERIC[r.type] ?? sentence(r.type.replace(/_/g, " "));
  switch (r.type) {
    case "duration_between":
      return isNum(p.min_s) && isNum(p.max_s)
        ? `Runs ${num(p.min_s)}–${num(p.max_s)} seconds`
        : generic;
    case "brightness_range":
      return "Neither too dark nor blown out";
    case "flicker_below":
      return "Brightness holds steady — no flicker";
    case "scene_cuts":
      if (!isNum(p.max)) return generic;
      return p.max === 0
        ? "One continuous take — no cuts"
        : `At most ${num(p.max)} cut${p.max === 1 ? "" : "s"} mid-shot`;
    case "camera_motion": {
      const d = typeof p.direction === "string" ? p.direction : "";
      if (!d) return generic;
      if (d === "static") return "Camera holds still";
      if (d === "any") return "Camera moves";
      // Film language, not axis language: left/right is a pan, up/down is a tilt.
      return d === "up" || d === "down" ? `Camera tilts ${d}` : `Camera pans ${d}`;
    }
    case "palette_deltae":
      return "Stays on the brand palette";
    case "subject_present":
      return p.subject ? sentence(`${humanizeSubject(p.subject)} is in frame`) : generic;
    case "identity_consistent":
      return p.subject
        ? sentence(`${humanizeSubject(p.subject)} looks the same throughout`)
        : generic;
    case "action_completed":
      return p.action ? `Completes on screen: ${String(p.action)}` : generic;
    case "title_card_present":
      return "A title card is visible";
    default:
      return generic;
  }
}

/** Rule packs. The YAML filename is the id; a person picking one wants to know what
 *  kind of show it protects, not what the file is called. */
export const PACK_LABEL: Record<string, string> = {
  short_drama: "Short drama — continuity",
  brand_rules: "Brand safety",
};

export const packLabel = (name: string) => PACK_LABEL[name] ?? name.replace(/[_-]+/g, " ");

/** Pipeline stages. The internal status is a state-machine token — the operator wants
 *  to know what is happening to their episode right now, in their own words. */
export const STAGE_LABEL: Record<string, string> = {
  queued: "Queued",
  scripting: "Writing the shot list",
  tier0: "Pre-screening stills",
  awaiting_review: "Waiting for you",
  drafting: "Drafting shots",
  verifying: "Checking the footage",
  repairing: "Repairing a shot",
  promoting: "Rendering finals",
  assembling: "Cutting the episode",
  done: "Finished",
  failed: "Stopped",
};

export const stageLabel = (status: string) => STAGE_LABEL[status] ?? status.replace(/_/g, " ");
