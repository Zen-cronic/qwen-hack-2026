import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import { mono, tokens } from "./theme";
import type { Metrics } from "./types";
import { shortLabel } from "./vocabulary";

const C = { pass: tokens.pass, fail: tokens.fail, inconclusive: tokens.inconclusive };
const tip = {
  contentStyle: { background: tokens.panel, border: `1px solid ${tokens.border}`, borderRadius: 8, color: tokens.text },
  labelStyle: { color: tokens.muted },
};

// Must stay in sync with the closed vocabulary in server/specs.py.
const TIER_A_TYPES = new Set([
  "duration_between", "brightness_range", "flicker_below", "scene_cuts", "camera_motion", "palette_deltae",
]);
const TIER_B_TYPES = new Set(["identity_consistent", "action_completed", "title_card_present"]);

function Tile({ v, k }: { v: string; k: string }) {
  return (
    <Paper sx={{ p: "14px 16px" }}>
      <Typography sx={{ fontFamily: mono, fontSize: 26, fontWeight: 700, fontVariantNumeric: "tabular-nums", lineHeight: 1.1 }}>{v}</Typography>
      <Typography color="text.secondary" sx={{ fontSize: 12, mt: 0.25 }}>{k}</Typography>
    </Paper>
  );
}

// Identity is never color-alone: every multi-series chart carries this key.
function Legend({ items }: { items: { c: string; label: string }[] }) {
  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, mt: -0.5, mb: 1 }}>
      {items.map((it) => (
        <Box key={it.label} sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ width: 9, height: 9, borderRadius: "2px", bgcolor: it.c }} />
          <Typography sx={{ fontSize: 11, color: "text.secondary" }}>{it.label}</Typography>
        </Box>
      ))}
    </Box>
  );
}

export function ChartsPanel({ m }: { m: Metrics }) {
  // `label` is for the axis; `type` stays on the datum so the tooltip can cite the check.
  const heat = Object.entries(m.heatmap).map(([type, c]) => ({
    type, label: shortLabel(type), pass: c.pass, fail: c.fail, inconclusive: c.inconclusive,
  }));
  const frontier = m.frontier.map((f) => ({ ...f, quality: Math.round(f.quality * 100) }));

  // Every take as one point; (shot, take) is unique, so nothing overplots.
  const conv = m.convergence ?? [];
  const maxTake = conv.reduce((n, t) => Math.max(n, t.take), 0);
  const shotCount = conv.reduce((n, t) => Math.max(n, t.shot + 1), 0);
  const takeTicks = Array.from({ length: maxTake + 1 }, (_, i) => i);
  const shotTicks = Array.from({ length: shotCount }, (_, i) => i);

  // Decision-relevant headline numbers, derived from the same metrics block.
  const cells = Object.entries(m.heatmap);
  const defectsCaught = cells.reduce((n, [, c]) => n + c.fail, 0);
  const tierA = cells.reduce((n, [t, c]) => n + (TIER_A_TYPES.has(t) ? c.total : 0), 0);
  const tierB = cells.reduce((n, [t, c]) => n + (TIER_B_TYPES.has(t) ? c.total : 0), 0);

  // Nothing to chart before the first take — a wall of empty panels reads as broken.
  if (heat.length === 0 && frontier.length === 0 && conv.length === 0) return null;

  return (
    <Box data-testid="charts">
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" }, gap: 1.5, mb: 2.5 }}>
        <Tile v={m.cost_per_passing_second == null ? "—" : `$${m.cost_per_passing_second.toFixed(2)}`} k="cost / passing sec" />
        <Tile v={`${defectsCaught}`} k="defects caught" />
        <Tile v={`${tierA} / ${tierB}`} k="tier-A / tier-B checks" />
        <Tile v={`${m.repair.repair_successes}/${m.repair.shots_repaired}`} k="repairs succeeded" />
      </Box>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2.5, mb: 2.5 }}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="h3" gutterBottom>Assertion pass-rate — an empirical capability map</Typography>
          {heat.length === 0 ? <Typography color="text.secondary">No verifications yet.</Typography> : (
            <>
              <Legend items={[{ c: C.pass, label: "pass" }, { c: C.fail, label: "fail" }, { c: C.inconclusive, label: "inconclusive" }]} />
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={heat} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="label" width={150} tick={{ fill: tokens.muted, fontSize: 11 }} />
                  <Tooltip {...tip} />
                  <Bar dataKey="pass" stackId="a" fill={C.pass} isAnimationActive={false} />
                  <Bar dataKey="fail" stackId="a" fill={C.fail} isAnimationActive={false} />
                  <Bar dataKey="inconclusive" stackId="a" fill={C.inconclusive} radius={[0, 3, 3, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}
        </Paper>

        <Paper sx={{ p: 2 }}>
          <Typography variant="h3" gutterBottom>Cost–quality frontier (per shot)</Typography>
          {frontier.length === 0 ? <Typography color="text.secondary">No takes yet — the frontier fills in as drafts render.</Typography> : (
            <>
              <Legend items={[{ c: C.pass, label: "certified" }, { c: C.fail, label: "not certified" }]} />
              <ResponsiveContainer width="100%" height={240}>
                <ScatterChart margin={{ left: 0, bottom: 12 }}>
                  <CartesianGrid stroke={tokens.border} />
                  {/* X is PRODUCTION cost, not this run's bill — a warm re-verify bills 0.
                      Axis padding is load-bearing: quality=100 points would clip. */}
                  <XAxis type="number" dataKey="production_seconds" name="production cost"
                    padding={{ left: 22, right: 22 }} tick={{ fill: tokens.muted, fontSize: 11 }}
                    label={{ value: "production cost (video s)", fill: tokens.muted, fontSize: 11, position: "insideBottom", offset: -6 }} />
                  <YAxis type="number" dataKey="quality" name="quality" domain={[0, 108]}
                    ticks={[0, 25, 50, 75, 100]} tick={{ fill: tokens.muted, fontSize: 11 }} />
                  <ZAxis range={[90, 90]} />
                  <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} />
                  <Scatter data={frontier} isAnimationActive={false}>
                    {frontier.map((f, i) => <Cell key={i} fill={f.certified ? C.pass : C.fail} />)}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              {frontier.some((f) => f.replayed) && (
                <Typography color="text.secondary" sx={{ fontSize: 11, mt: 0.5 }} data-testid="frontier-replay-note">
                  ⟳ served from the content-addressed cache — production cost shown; this run
                  billed {frontier.reduce((n, f) => n + f.cost_seconds, 0)} video-seconds
                </Typography>
              )}
            </>
          )}
        </Paper>
      </Box>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h3" gutterBottom>Repair convergence — every take, per shot</Typography>
        {conv.length === 0 ? <Typography color="text.secondary">No takes yet.</Typography> : (
          <>
            <Legend items={[{ c: C.pass, label: "take passed" }, { c: C.fail, label: "take failed" }]} />
            <ResponsiveContainer width="100%" height={Math.max(150, shotCount * 44)}>
              <ScatterChart margin={{ left: 0, bottom: 12, right: 16 }}>
                <CartesianGrid stroke={tokens.border} />
                <XAxis type="number" dataKey="take" name="take" domain={[-0.5, maxTake + 0.5]}
                  ticks={takeTicks} allowDecimals={false} tick={{ fill: tokens.muted, fontSize: 11 }}
                  label={{ value: "take", fill: tokens.muted, fontSize: 11, position: "insideBottom", offset: -6 }} />
                <YAxis type="number" dataKey="shot" name="shot" reversed domain={[-0.5, shotCount - 0.5]}
                  ticks={shotTicks} allowDecimals={false} width={62}
                  tick={{ fill: tokens.muted, fontSize: 11 }} tickFormatter={(v) => `shot ${v}`} />
                <ZAxis range={[110, 110]} />
                <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={conv} isAnimationActive={false}>
                  {conv.map((t, i) => <Cell key={i} fill={t.passed ? C.pass : C.fail} />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
            <Typography color="text.secondary" sx={{ fontSize: 12, mt: 0.5 }}>
              A red take followed by a green one on the same row is the repair loop converging:
              the blocking Tier-A failure fed back into a new prompt, and the retake passed.
            </Typography>
          </>
        )}
      </Paper>
    </Box>
  );
}
