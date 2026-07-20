import { Fragment, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { alpha, styled } from "@mui/material/styles";
import { mediaUrl } from "./api";
import { mono, statusColor, tokens } from "./theme";
import { checkLabel, packLabel, stageLabel } from "./vocabulary";
import type { AssertionResult, Pack, ShotState, Take, Wallet, Project } from "./types";

// Flat bordered surface — the repeated "panel" from the old CSS, now one component.
const Panel = styled(Paper)({ padding: "18px 20px", marginBottom: 20 });

// A measurement reads like a test-report line: mono value over an overline label.
function Cell({ v, k }: { v: string | number; k: string }) {
  return (
    <Box sx={{ textAlign: "right" }}>
      <Typography sx={{ fontFamily: mono, fontWeight: 600, fontVariantNumeric: "tabular-nums", lineHeight: 1.15 }}>{v}</Typography>
      <Typography variant="overline" component="div" color="text.secondary" sx={{ textTransform: "uppercase" }}>{k}</Typography>
    </Box>
  );
}

export function WalletMeter({ w, judge }: { w: Wallet; judge?: { judge_mode: boolean } }) {
  return (
    <Stack direction="row" spacing={1.75} data-testid="wallet" sx={{ alignItems: "center", flexWrap: "wrap" }}>
      <Cell v={w.draft_clips} k="drafts" />
      <Cell v={w.final_clips} k="finals" />
      {w.patch_clips > 0 && <Cell v={w.patch_clips} k="patches" />}
      <Cell v={w.images} k="stills" />
      <Cell v={(w.tokens_in + w.tokens_out).toLocaleString()} k="tokens" />
      <Cell v={`$${w.est_usd.toFixed(2)}`} k="est. cost" />
      {judge?.judge_mode && <Chip size="small" variant="outlined" label="judge mode" />}
    </Stack>
  );
}

// One-click starting points: a cold visitor (or judge) should reach a running
// pipeline without composing a premise first.
const SAMPLE_PREMISES = [
  "a lonely lighthouse keeper who discovers a message in a bottle",
  "a street cat assembles a crew for a fish-market heist",
  "a night-shift robot barista perfects latte art for its last customer",
];

// The signature element: the closed assertion vocabulary as faint ambient texture
// behind the hero. Honest (it is the real grammar from server/specs.py) and only
// possible for a product that has a grammar. Decorative: hidden from the a11y tree,
// never intercepts clicks, static.
const AMBIENT_VOCAB: { t: string; sx: object }[] = [
  { t: "Runs 4–6 seconds", sx: { top: "7%", left: "2%", transform: "rotate(-7deg)" } },
  { t: "Neither too dark nor blown out", sx: { top: "24%", left: "5%", transform: "rotate(4deg)" } },
  { t: "Brightness holds steady", sx: { top: "41%", left: "1%", transform: "rotate(-4deg)" } },
  { t: "One continuous take", sx: { top: "57%", left: "6%", transform: "rotate(6deg)" } },
  { t: "Camera pans right", sx: { top: "72%", left: "2%", transform: "rotate(-6deg)" } },
  { t: "Stays on the brand palette", sx: { bottom: "5%", left: "8%", transform: "rotate(3deg)" } },
  { t: "The keeper is in frame", sx: { top: "9%", right: "3%", transform: "rotate(5deg)" } },
  { t: "Same subject throughout", sx: { top: "26%", right: "7%", transform: "rotate(-5deg)" } },
  { t: "The action completes", sx: { top: "43%", right: "2%", transform: "rotate(4deg)" } },
  { t: "A title card is visible", sx: { top: "59%", right: "6%", transform: "rotate(-3deg)" } },
  { t: "Checked before it ships", sx: { top: "75%", right: "3%", transform: "rotate(6deg)" } },
  { t: "Rejected before it costs", sx: { bottom: "6%", right: "9%", transform: "rotate(-5deg)" } },
];

function AmbientVocab() {
  return (
    <Box aria-hidden sx={{
      position: "absolute", inset: 0, overflow: "hidden", zIndex: 0,
      pointerEvents: "none", userSelect: "none", display: { xs: "none", sm: "block" },
    }}>
      {AMBIENT_VOCAB.map((v) => (
        <Typography key={v.t} component="span" sx={{
          position: "absolute", fontFamily: mono, fontSize: 12, whiteSpace: "nowrap",
          color: alpha(tokens.text, 0.09), ...v.sx,
        }}>{v.t}</Typography>
      ))}
    </Box>
  );
}

export function NewProject({ packs, busy, onCreate }: {
  packs: Pack[]; busy: boolean;
  onCreate: (premise: string, pack: string, maxShots: number, customChecks: string[]) => void;
}) {
  const [premise, setPremise] = useState(SAMPLE_PREMISES[0]);
  const [pack, setPack] = useState("short_drama");
  const [maxShots, setMaxShots] = useState(3);
  const [customChecks, setCustomChecks] = useState("");
  // Default-open: the checks field is part of the pitch (author your own checks),
  // not an afterthought behind a disclosure.
  const [checksOpen, setChecksOpen] = useState(true);
  const submit = () =>
    onCreate(premise, pack, maxShots, customChecks.split("\n").map((s) => s.trim()).filter(Boolean));
  return (
    <Box sx={{ position: "relative", pt: { xs: 4, sm: 8 }, pb: { xs: 4, sm: 6 } }}>
      <AmbientVocab />
      <Box sx={{ position: "relative", zIndex: 1, maxWidth: 800, mx: "auto" }}>
        <Typography variant="h1" sx={{
          fontSize: "clamp(2rem, 4.5vw, 3.1rem)", letterSpacing: "-0.03em",
          lineHeight: 1.08, textAlign: "center", mb: 2,
        }}>
          Turn a premise into a{" "}
          <Box component="span" sx={{ color: tokens.pass }}>certified</Box> episode.
        </Typography>
        <Typography color="text.secondary" sx={{ textAlign: "center", maxWidth: 640, mx: "auto", mb: 4.5 }}>
          Dailies writes the shot list, turns it into rules each shot has to pass, and renders.
          The cheap checks run on every take because they cost nothing — a clip only joins the
          episode once it has passed them.
        </Typography>

        <Paper sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: "16px" }}>
          <TextField
            variant="standard" multiline minRows={2} fullWidth
            value={premise} onChange={(e) => setPremise(e.target.value)}
            placeholder="What should this episode be about?"
            slotProps={{
              input: { disableUnderline: true, sx: { fontSize: 17, lineHeight: 1.45, px: 0.5, py: 0.5 } },
              htmlInput: { "data-testid": "premise", "aria-label": "Premise" },
            }}
          />
          <Stack direction="row" spacing={1.25} useFlexGap
            sx={{ flexWrap: "wrap", alignItems: "center", mt: 1.5, pt: 1.5, borderTop: 1, borderColor: "divider" }}>
            <TextField
              select label="Rules" size="small" value={pack} onChange={(e) => setPack(e.target.value)}
              sx={{ minWidth: 215 }}
              slotProps={{ htmlInput: { "data-testid": "pack" } }}
            >
              {packs.map((p) => (
                <MenuItem key={p.name} value={p.name}>
                  {packLabel(p.name)} · {p.defaults} checks
                </MenuItem>
              ))}
            </TextField>
            <TextField
              type="number" label="Shots" size="small" value={maxShots}
              onChange={(e) => setMaxShots(Number(e.target.value))} sx={{ width: 84 }}
              slotProps={{ htmlInput: { min: 1, max: 12 } }}
            />
            <Button variant="text" color="inherit" size="small" onClick={() => setChecksOpen((o) => !o)}
              sx={{ color: "text.secondary", fontWeight: 600 }}>
              Custom checks {checksOpen ? "▴" : "▾"}
            </Button>
            <Box sx={{ flexGrow: 1 }} />
            <Button disabled={busy || !premise.trim()} data-testid="create" onClick={submit}>
              {busy ? "Compiling…" : "Compile & generate"}
            </Button>
          </Stack>
          <Collapse in={checksOpen}>
            <TextField
              label="Custom checks (one per line — optional)" multiline minRows={2}
              value={customChecks} onChange={(e) => setCustomChecks(e.target.value)}
              placeholder={"a title card must be visible\nthe camera should pan right"}
              helperText={"Written however you'd say it. Anything we can't measure yet — audio, "
                + "on-screen text, “the first three seconds” — is left out rather than faked."}
              sx={{ mt: 2, width: "100%" }}
              slotProps={{ htmlInput: { "data-testid": "custom-checks" } }}
            />
          </Collapse>
        </Paper>

        <Stack direction="row" spacing={0.75} useFlexGap
          sx={{ flexWrap: "wrap", justifyContent: "center", mt: 2.5 }}>
          {SAMPLE_PREMISES.map((s) => (
            <Chip key={s} size="small" variant="outlined" label={s} onClick={() => setPremise(s)}
              sx={{ maxWidth: "100%", height: "auto", py: 0.4, color: "text.secondary", "& .MuiChip-label": { whiteSpace: "normal" } }} />
          ))}
        </Stack>
      </Box>
    </Box>
  );
}

// The ten internal stages, grouped into the five phases a user actually follows.
// The pill stays coarse; the caption underneath stays precise (raw stage + detail).
const PHASES: { label: string; stages: string[] }[] = [
  { label: "Script", stages: ["queued", "scripting"] },
  { label: "Stills", stages: ["tier0"] },
  { label: "Review", stages: ["awaiting_review"] },
  { label: "Takes", stages: ["drafting", "verifying", "repairing", "promoting"] },
  { label: "Cut", stages: ["assembling", "done"] },
];

function PhasePill({ label, state }: { label: string; state: "idle" | "active" | "done" | "failed" }) {
  const base = {
    display: "inline-flex", alignItems: "center", gap: 0.75, fontSize: 13,
    px: 1.75, py: "6px", borderRadius: 999, border: 1,
    borderColor: "divider", color: "text.secondary", whiteSpace: "nowrap",
  } as const;
  const variants = {
    idle: {},
    active: { bgcolor: "primary.main", color: "primary.contrastText", borderColor: "primary.main", fontWeight: 600 },
    done: { color: "success.main", borderColor: alpha(tokens.pass, 0.4), bgcolor: alpha(tokens.pass, 0.08) },
    failed: { bgcolor: "error.main", color: "error.contrastText", borderColor: "error.main", fontWeight: 600 },
  };
  return (
    <Box component="span" sx={{ ...base, ...variants[state] }}>
      {state === "active" && (
        <Box component="span" sx={{
          width: 7, height: 7, borderRadius: "50%", bgcolor: "currentColor",
          animation: "dailies-pulse 1.6s ease-in-out infinite",
          "@keyframes dailies-pulse": { "0%, 100%": { opacity: 1 }, "50%": { opacity: 0.35 } },
        }} />
      )}
      {state === "done" && <Box component="span" sx={{ fontSize: 11 }}>✓</Box>}
      {label}
    </Box>
  );
}

// What each stage is doing, in the user's terms — the poll loop makes these live captions.
const STAGE_CAPTIONS: Record<string, string> = {
  queued: "The run starts in a moment.",
  scripting: "The script agent is writing shots and their machine-checkable assertions.",
  tier0: "Tier-0 — screening pre-render stills at ~1/25th of video cost.",
  awaiting_review: "Paused at the one human gate. Nothing has spent video budget yet.",
  drafting: "Rendering draft clips on the budget tier.",
  verifying: "Running the checklist: deterministic CV first (zero tokens), VLM advisory on top.",
  repairing: "A shot failed its contract — feeding the failure back into a retake prompt.",
  promoting: "Approved takes re-render as a frame-anchored final — continuous with the take you saw.",
  assembling: "Cutting the certified episode with ffmpeg.",
  done: "Every shipped clip passed its contract.",
  failed: "Something went wrong — details above.",
};

export function Pipeline({ status }: { status: string }) {
  const done = status === "done";
  const cur = PHASES.findIndex((p) => p.stages.includes(status));
  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" spacing={1} useFlexGap data-testid="pipeline"
        sx={{ flexWrap: "wrap", alignItems: "center" }}>
        {PHASES.map((p, i) => {
          const state = status === "failed" ? "idle" : done || i < cur ? "done" : i === cur ? "active" : "idle";
          return (
            <Fragment key={p.label}>
              {i > 0 && <Box component="span" sx={{ color: "text.secondary", fontSize: 12, userSelect: "none" }}>›</Box>}
              <PhasePill label={p.label} state={state} />
            </Fragment>
          );
        })}
        {status === "failed" && <PhasePill label="failed" state="failed" />}
      </Stack>
      {STAGE_CAPTIONS[status] && (
        <Typography data-testid="stage-caption" variant="body2" color="text.secondary"
          sx={{ mt: 1, fontFamily: mono, fontSize: 12.5 }}>
          <Box component="span" sx={{ color: "text.primary", fontWeight: 600 }}>{stageLabel(status)}</Box>
          {" — "}{STAGE_CAPTIONS[status]}
        </Typography>
      )}
    </Box>
  );
}

export function ReviewBar({ onApprove, shots }: { onApprove: () => void; shots?: ShotState[] }) {
  // Tier-0 evidence summary: what the pre-render screen actually measured, so the
  // approve decision is informed rather than a blind unlock.
  const t0 = (shots ?? []).flatMap((s) => s.tier0_results);
  const t0pass = t0.filter((r) => r.status === "pass").length;
  const summary = t0.length
    ? `Tier-0 screened ${t0.length} still check${t0.length === 1 ? "" : "s"}: ${t0pass} passed${t0.length - t0pass ? `, ${t0.length - t0pass} flagged` : ""}.`
    : "Tier-0 stills are ready.";
  return (
    <Paper data-testid="reviewbar" sx={{
      p: { xs: 2.5, sm: 3.5 }, mb: 2.5, border: 1, borderColor: "warning.main", borderRadius: "16px",
      background: `linear-gradient(135deg, ${alpha(tokens.inconclusive, 0.12)}, transparent 55%)`,
    }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2.5}
        sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}>
        <Box>
          <Typography variant="overline" sx={{ color: "warning.main", letterSpacing: "0.08em" }}>
            The one human gate
          </Typography>
          <Typography sx={{ fontSize: { xs: 20, sm: 23 }, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.2, mb: 0.75 }}>
            Review the shot list before spending video budget
          </Typography>
          <Typography variant="body2" color="text.secondary" data-testid="tier0-summary">
            {summary} Approve to start drafting — nothing has spent a video-second yet.
          </Typography>
        </Box>
        <Button size="large" data-testid="approve" onClick={onApprove}
          sx={{ flexShrink: 0, px: 3.5, py: 1.25 }}>Approve &amp; generate</Button>
      </Stack>
    </Paper>
  );
}

/** Where in the clip a check failed, when Tier-A could localize it. `measured` is an
 *  open bag from the server, so the shape is verified before it's trusted. */
function failWindow(r: AssertionResult): [number, number] | null {
  const raw = r.measured?.fail_window_s;
  if (!Array.isArray(raw) || raw.length !== 2) return null;
  const [lo, hi] = raw;
  return typeof lo === "number" && typeof hi === "number" ? [lo, hi] : null;
}

function Check({ r, onVerdict }: { r: AssertionResult; onVerdict?: (v: string) => void }) {
  const canOverride = r.advisory && onVerdict && (r.status === "inconclusive" || r.status === "fail");
  const win = failWindow(r);
  return (
    <Stack direction="row" spacing={1.25} sx={{ alignItems: "flex-start" }}>
      <Box sx={{ width: 9, height: 9, borderRadius: "50%", mt: "4px", flex: "none", bgcolor: statusColor(r.status) }} />
      <Box sx={{ minWidth: 0 }}>
        <Box>
          {/* The machine name is the reproducibility receipt, but it is not display copy —
              it rides on `title` for anyone who goes looking, and the visible badge says
              the thing a person actually needs: was this measured, or judged? */}
          <Typography component="span" title={r.type} sx={{ fontSize: 12.5, fontWeight: 600 }}>{checkLabel(r)}</Typography>
          <Box component="span" sx={{ fontSize: 9, color: "text.secondary", border: 1, borderColor: "divider", borderRadius: "4px", px: 0.5, ml: 0.75 }}>
            {r.advisory ? "advisory" : "measured"}
          </Box>
        </Box>
        {r.detail && <Typography sx={{ fontFamily: mono, fontSize: 11.5, color: "text.secondary" }}>{r.detail}</Typography>}
        {win && (
          <Box component="span" data-testid="fail-window" sx={{
            display: "inline-block", mt: 0.35, fontFamily: mono, fontSize: 10.5,
            color: statusColor(r.status), borderRadius: "4px", px: 0.6, py: 0.15,
            border: 1, borderColor: alpha(statusColor(r.status), 0.4),
            bgcolor: alpha(statusColor(r.status), 0.1),
          }}>
            fails {win[0].toFixed(1)}s → {win[1].toFixed(1)}s
          </Box>
        )}
        {canOverride && (
          <Stack direction="row" spacing={0.75} sx={{ mt: 0.5 }}>
            <Button size="small" variant="outlined" color="inherit" sx={{ fontSize: 10, py: 0.25, px: 1 }} onClick={() => onVerdict!("pass")}>mark pass</Button>
            <Button size="small" variant="outlined" color="inherit" sx={{ fontSize: 10, py: 0.25, px: 1 }} onClick={() => onVerdict!("fail")}>mark fail</Button>
          </Stack>
        )}
      </Box>
    </Stack>
  );
}

const badgeSx = (badge: string) => {
  const c = statusColor(badge);
  return { bgcolor: alpha(c, 0.16), color: c, border: 1, borderColor: alpha(c, 0.4), fontSize: 11 };
};

// Mirrors ANCHOR_LEAD_S in server/patch.py: the button names the second the server
// will actually anchor at, so the label is a promise rather than an approximation.
const ANCHOR_LEAD_S = 0.2;

export function ShotCard({ shot, onVerdict, onPatch }: {
  shot: ShotState;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
  onPatch?: (shotIndex: number) => Promise<void>;
}) {
  const takes = shot.takes;
  const [sel, setSel] = useState<number>(-1);
  const [patching, setPatching] = useState(false);
  const activeIdx = sel < 0 ? takes.length - 1 : sel;
  const take: Take | undefined = takes.length ? takes[activeIdx] : undefined;
  const results = take ? take.results : shot.tier0_results;
  const thumb = take?.results.find((r) => r.evidence.length)?.evidence[0] ?? shot.still_path;
  const badge = shot.certified ? "certified" : shot.status === "failed" ? "failed" : "working";

  // Patching always acts on the LATEST take, so the offer is keyed to that one — not
  // to whichever take the user happens to be inspecting.
  const latest = takes.length ? takes[takes.length - 1] : undefined;
  const target = latest?.results.find((r) => !r.advisory && r.status === "fail" && failWindow(r));
  const anchorS = target ? Math.max(0, failWindow(target)![0] - ANCHOR_LEAD_S) : 0;

  const doPatch = async () => {
    setPatching(true);
    try { await onPatch!(shot.spec.index); } finally { setPatching(false); }
  };

  return (
    <Paper data-testid="shot" id={`shot-card-${shot.spec.index}`} sx={{ overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {thumb ? (
        <Box component="img" alt={`shot ${shot.spec.index}`} src={mediaUrl(thumb)}
          sx={{ aspectRatio: "16 / 9", width: "100%", objectFit: "cover", bgcolor: "#000", display: "block" }} />
      ) : (
        <Box sx={{
          aspectRatio: "16 / 9", width: "100%", bgcolor: "background.default",
          display: "flex", alignItems: "center", justifyContent: "center",
          borderBottom: 1, borderColor: "divider",
        }}>
          <Typography sx={{ fontFamily: mono, fontSize: 11, color: "text.secondary" }}>awaiting first frame…</Typography>
        </Box>
      )}
      <Box sx={{ p: 1.75, display: "flex", flexDirection: "column", gap: 1.25 }}>
        <Stack direction="row" spacing={1} sx={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <Box>
            <Typography sx={{ fontSize: 12, color: "text.secondary" }}>
              Shot {shot.spec.index}{shot.spec.subject ? ` · ${shot.spec.subject}` : ""}
            </Typography>
            <Typography sx={{ fontSize: 13, lineHeight: 1.4 }}>{shot.spec.prompt}</Typography>
          </Box>
          <Chip size="small" label={badge} data-testid="shot-badge" sx={{ ...badgeSx(badge), flexShrink: 0 }} />
        </Stack>

        {takes.length > 1 && (
          <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: "wrap" }}>
            {takes.map((t, i) => (
              <ButtonBase key={i} onClick={() => setSel(i)} sx={{
                display: "flex", flexDirection: "column", alignItems: "flex-start",
                fontSize: 11, fontFamily: mono, px: 1.1, py: 0.5, borderRadius: "6px",
                bgcolor: "background.default", border: 1,
                borderColor: activeIdx === i ? "primary.main" : "divider",
                color: activeIdx === i ? "text.primary" : "text.secondary",
              }}>
                <Box component="span" sx={{ fontSize: 9, textTransform: "uppercase" }}>{t.tier}</Box>
                take {t.take_no}{t.passed === false ? " ✕" : t.passed ? " ✓" : ""}
              </ButtonBase>
            ))}
          </Stack>
        )}

        <Stack spacing={0.9}>
          {results.length === 0 && <Typography variant="body2" color="text.secondary">No checks yet.</Typography>}
          {results.map((r, i) => (
            <Check key={i} r={r} onVerdict={(v) => onVerdict(shot.spec.index, r.type, v)} />
          ))}
        </Stack>

        {target && onPatch && (
          <Box sx={{
            mt: 0.25, pt: 1.25, borderTop: 1, borderColor: "divider",
            display: "flex", alignItems: "center", gap: 1.25, flexWrap: "wrap",
          }}>
            <Button size="small" variant="outlined" color="inherit" data-testid="patch"
              disabled={patching} onClick={doPatch}
              sx={{ fontFamily: mono, fontSize: 10.5, py: 0.3, px: 1.2, flexShrink: 0 }}>
              {patching ? "patching…" : `patch from ${anchorS.toFixed(1)}s`}
            </Button>
            <Typography sx={{ fontFamily: mono, fontSize: 10.5, color: "text.secondary" }}>
              {patching
                ? "re-rendering from the last good frame, then re-verifying"
                : `re-render this shot only — not yet true: ${checkLabel(target)}`}
            </Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
}

export function ConformanceBoard({ project, onVerdict, onPatch }: {
  project: Project;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
  onPatch?: (shotIndex: number) => Promise<void>;
}) {
  return (
    <Panel>
      <Typography variant="h2" gutterBottom>Conformance board</Typography>
      <Box data-testid="board" sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 2 }}>
        {project.shots.length === 0 && <Typography color="text.secondary">Waiting for the script agent…</Typography>}
        {project.shots.map((s) => (
          <ShotCard key={s.spec.index} shot={s} onVerdict={onVerdict} onPatch={onPatch} />
        ))}
      </Box>
    </Panel>
  );
}

// The episode file keeps a stable path (episode.mp4), but its BYTES change whenever a
// shot is patched and the cut is re-concatenated. Without a changing URL the <video>
// element replays the browser-cached old cut — the patched clip, and its restored
// narration, would never appear. Key the URL on the certified takes so it changes
// exactly when the episode does.
function episodeSrc(project: Project): string {
  const base = mediaUrl(project.episode_path);
  if (!base) return "";
  const rev = project.shots.map((s) => s.final_path ?? "").join("|");
  let h = 5381;
  for (let i = 0; i < rev.length; i++) h = ((h << 5) + h + rev.charCodeAt(i)) | 0;
  return `${base}?rev=${(h >>> 0).toString(36)}`;
}

/** Who speaks, and in whose voice.
 *
 *  Read straight off `project.cast`, which the server fixed at scripting — so this is the
 *  mapping the narration actually used, not one reconstructed here from the shot list.
 *  A single-narrator episode has no cast to show and renders nothing.
 */
function CastRow({ cast }: { cast: Record<string, string> }) {
  const members = Object.entries(cast ?? {});
  if (!members.length) return null;
  return (
    <Stack direction="row" spacing={1} data-testid="cast"
      sx={{ mt: 1.5, alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
      <Typography variant="overline" sx={{ color: "text.secondary", letterSpacing: "0.08em" }}>
        Cast
      </Typography>
      {members.map(([who, voice]) => (
        <Chip key={who} size="small" data-testid="cast-chip" label={
          <Fragment>
            {who}
            <Box component="span" sx={{ fontFamily: mono, color: tokens.muted, ml: 0.75 }}>
              {voice}
            </Box>
          </Fragment>
        } sx={{ bgcolor: alpha(tokens.accent, 0.1), border: 1,
                borderColor: alpha(tokens.accent, 0.28), fontSize: 11 }} />
      ))}
    </Stack>
  );
}

export function FinalCut({ project }: { project: Project }) {
  const [copied, setCopied] = useState(false);
  if (!project.episode_path) return null;
  const src = episodeSrc(project);
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard unavailable (http, permissions) — button just stays quiet */ }
  };
  return (
    <Panel data-testid="finalcut">
      <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", mb: 1.25 }}>
        <Typography variant="h2">Certified episode</Typography>
        <Chip size="small" label="every contract passed" sx={badgeSx("certified")} />
      </Stack>
      <Box component="video" controls src={src}
        sx={{ width: "100%", borderRadius: "10px", bgcolor: "#000", display: "block" }} />
      <CastRow cast={project.cast} />
      <Stack direction="row" spacing={1.5} sx={{ mt: 1.25, alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 260 }}>
          {project.metrics.summary.certified}/{project.metrics.summary.shots_total} shots certified ·
          re-verifies from cache at zero video cost.
        </Typography>
        <Button size="small" variant="outlined" color="inherit" data-testid="copylink" onClick={copyLink}>
          {copied ? "Link copied ✓" : "Copy report link"}
        </Button>
        <Button size="small" variant="outlined" color="inherit" component="a"
          href={src} download="dailies-episode.mp4">
          Download episode
        </Button>
      </Stack>
    </Panel>
  );
}
