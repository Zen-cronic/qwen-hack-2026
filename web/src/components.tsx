import { useState } from "react";
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
import type { AssertionResult, Pack, ShotState, Take, Wallet, Project } from "./types";

const STAGES = ["queued", "scripting", "tier0", "awaiting_review", "drafting",
  "verifying", "repairing", "promoting", "assembling", "done"];

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
  { t: "duration_between: [4.0, 6.0]", sx: { top: "7%", left: "2%", transform: "rotate(-7deg)" } },
  { t: "brightness_range: [25, 235]", sx: { top: "24%", left: "5%", transform: "rotate(4deg)" } },
  { t: "flicker_below: 22.0", sx: { top: "41%", left: "1%", transform: "rotate(-4deg)" } },
  { t: "scene_cuts: ≤ 1", sx: { top: "57%", left: "6%", transform: "rotate(6deg)" } },
  { t: "camera_motion: right", sx: { top: "72%", left: "2%", transform: "rotate(-6deg)" } },
  { t: "palette_deltae: mean ΔE*76 ≤ 30", sx: { bottom: "5%", left: "8%", transform: "rotate(3deg)" } },
  { t: "subject_present: the keeper", sx: { top: "9%", right: "3%", transform: "rotate(5deg)" } },
  { t: "identity_consistent", sx: { top: "26%", right: "7%", transform: "rotate(-5deg)" } },
  { t: "action_completed", sx: { top: "43%", right: "2%", transform: "rotate(4deg)" } },
  { t: "title_card_present", sx: { top: "59%", right: "6%", transform: "rotate(-3deg)" } },
  { t: "tier-A · zero tokens", sx: { top: "75%", right: "3%", transform: "rotate(6deg)" } },
  { t: "reject before spend", sx: { bottom: "6%", right: "9%", transform: "rotate(-5deg)" } },
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
          Dailies writes the shot list and compiles it into machine-checkable assertions.
          Every rendered clip must pass that contract — deterministic CV first, at zero
          token cost — before it can be promoted into the episode.
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
              select label="Assertion pack" size="small" value={pack} onChange={(e) => setPack(e.target.value)}
              sx={{ minWidth: 175 }}
              slotProps={{ htmlInput: { "data-testid": "pack" } }}
            >
              {packs.map((p) => <MenuItem key={p.name} value={p.name}>{p.name} ({p.defaults})</MenuItem>)}
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
              helperText="Plain-language rules compile to the closed vocabulary; anything unsupported (audio, on-screen text, time windows) is omitted."
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

function Stage({ label, state }: { label: string; state: "idle" | "active" | "done" | "failed" }) {
  const base = {
    fontSize: 11, px: 1.25, py: "5px", borderRadius: "6px", border: 1,
    borderColor: "divider", color: "text.secondary", whiteSpace: "nowrap",
  } as const;
  const variants = {
    idle: {},
    active: { bgcolor: "primary.main", color: "primary.contrastText", borderColor: "primary.main", fontWeight: 650 },
    done: { color: "success.main", borderColor: alpha(tokens.pass, 0.4) },
    failed: { bgcolor: "error.main", color: "error.contrastText", borderColor: "error.main", fontWeight: 650 },
  };
  return <Box component="span" sx={{ ...base, ...variants[state] }}>{label}</Box>;
}

// What each stage is doing, in the user's terms — the poll loop makes these live captions.
const STAGE_CAPTIONS: Record<string, string> = {
  queued: "Queued — the run starts in a moment.",
  scripting: "The script agent is writing shots and their machine-checkable assertions.",
  tier0: "Tier-0 — screening pre-render stills at ~1/25th of video cost.",
  awaiting_review: "Paused at the one human gate. Nothing has spent video budget yet.",
  drafting: "Rendering draft clips on the budget tier.",
  verifying: "Running the checklist: deterministic CV first (zero tokens), VLM advisory on top.",
  repairing: "A shot failed its contract — feeding the failure back into a retake prompt.",
  promoting: "Certified shots re-render on the premium tier.",
  assembling: "Cutting the certified episode with ffmpeg.",
  done: "Done — every shipped clip passed its contract.",
  failed: "The run failed — details above.",
};

export function Pipeline({ status }: { status: string }) {
  const cur = STAGES.indexOf(status);
  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" spacing={0.75} useFlexGap data-testid="pipeline" sx={{ flexWrap: "wrap" }}>
        {STAGES.map((s, i) => {
          const state = status === "failed" ? "idle" : i < cur ? "done" : i === cur ? "active" : "idle";
          return <Stage key={s} label={s} state={state} />;
        })}
        {status === "failed" && <Stage label="failed" state="failed" />}
      </Stack>
      {STAGE_CAPTIONS[status] && (
        <Typography data-testid="stage-caption" variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
          {STAGE_CAPTIONS[status]}
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
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2,
      p: "14px 18px", mb: 2.5, border: 1, borderColor: "warning.main",
      background: `linear-gradient(90deg, ${alpha(tokens.inconclusive, 0.14)}, transparent)`,
    }}>
      <Box>
        <Typography sx={{ fontWeight: 650 }}>Review the shot list before spending video budget</Typography>
        <Typography variant="body2" color="text.secondary" data-testid="tier0-summary">
          {summary} This is the one human gate — approve to start drafting.
        </Typography>
      </Box>
      <Button data-testid="approve" onClick={onApprove} sx={{ flexShrink: 0 }}>Approve &amp; generate</Button>
    </Paper>
  );
}

function Check({ r, onVerdict }: { r: AssertionResult; onVerdict?: (v: string) => void }) {
  const canOverride = r.advisory && onVerdict && (r.status === "inconclusive" || r.status === "fail");
  return (
    <Stack direction="row" spacing={1.25} sx={{ alignItems: "flex-start" }}>
      <Box sx={{ width: 9, height: 9, borderRadius: "50%", mt: "4px", flex: "none", bgcolor: statusColor(r.status) }} />
      <Box sx={{ minWidth: 0 }}>
        <Box>
          <Typography component="span" sx={{ fontSize: 12, fontWeight: 600 }}>{r.type}</Typography>
          {r.advisory && (
            <Box component="span" sx={{ fontSize: 9, color: "text.secondary", border: 1, borderColor: "divider", borderRadius: "4px", px: 0.5, ml: 0.5 }}>advisory</Box>
          )}
        </Box>
        {r.detail && <Typography sx={{ fontFamily: mono, fontSize: 11.5, color: "text.secondary" }}>{r.detail}</Typography>}
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

export function ShotCard({ shot, onVerdict }: {
  shot: ShotState;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
}) {
  const takes = shot.takes;
  const [sel, setSel] = useState<number>(-1);
  const activeIdx = sel < 0 ? takes.length - 1 : sel;
  const take: Take | undefined = takes.length ? takes[activeIdx] : undefined;
  const results = take ? take.results : shot.tier0_results;
  const thumb = take?.results.find((r) => r.evidence.length)?.evidence[0] ?? shot.still_path;
  const badge = shot.certified ? "certified" : shot.status === "failed" ? "failed" : "working";

  return (
    <Paper data-testid="shot" sx={{ overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <Box
        component={thumb ? "img" : "div"} alt={`shot ${shot.spec.index}`}
        src={thumb ? mediaUrl(thumb) : undefined}
        sx={{ aspectRatio: "16 / 9", width: "100%", objectFit: "cover", bgcolor: "#000", display: "block" }}
      />
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
      </Box>
    </Paper>
  );
}

export function ConformanceBoard({ project, onVerdict }: {
  project: Project;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
}) {
  return (
    <Panel>
      <Typography variant="h2" gutterBottom>Conformance board</Typography>
      <Box data-testid="board" sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 2 }}>
        {project.shots.length === 0 && <Typography color="text.secondary">Waiting for the script agent…</Typography>}
        {project.shots.map((s) => <ShotCard key={s.spec.index} shot={s} onVerdict={onVerdict} />)}
      </Box>
    </Panel>
  );
}

export function FinalCut({ project }: { project: Project }) {
  const [copied, setCopied] = useState(false);
  if (!project.episode_path) return null;
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard unavailable (http, permissions) — button just stays quiet */ }
  };
  return (
    <Panel data-testid="finalcut">
      <Typography variant="h2" gutterBottom>Certified episode</Typography>
      <Box component="video" controls src={mediaUrl(project.episode_path)}
        sx={{ width: "100%", borderRadius: "10px", bgcolor: "#000", display: "block" }} />
      <Stack direction="row" spacing={1.5} sx={{ mt: 1.25, alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 260 }}>
          {project.metrics.summary.certified}/{project.metrics.summary.shots_total} shots certified ·
          re-verifies from cache at zero video cost.
        </Typography>
        <Button size="small" variant="outlined" color="inherit" data-testid="copylink" onClick={copyLink}>
          {copied ? "Link copied ✓" : "Copy report link"}
        </Button>
        <Button size="small" variant="outlined" color="inherit" component="a"
          href={mediaUrl(project.episode_path)} download="dailies-episode.mp4">
          Download episode
        </Button>
      </Stack>
    </Panel>
  );
}
