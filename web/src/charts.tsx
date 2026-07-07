import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import { mono, tokens } from "./theme";
import type { Metrics } from "./types";

const C = { pass: tokens.pass, fail: tokens.fail, inconclusive: tokens.inconclusive };
const tip = {
  contentStyle: { background: tokens.panel, border: `1px solid ${tokens.border}`, borderRadius: 8, color: tokens.text },
  labelStyle: { color: tokens.muted },
};

function Tile({ v, k }: { v: string; k: string }) {
  return (
    <Paper sx={{ p: "14px 16px" }}>
      <Typography sx={{ fontFamily: mono, fontSize: 26, fontWeight: 700, fontVariantNumeric: "tabular-nums", lineHeight: 1.1 }}>{v}</Typography>
      <Typography color="text.secondary" sx={{ fontSize: 12, mt: 0.25 }}>{k}</Typography>
    </Paper>
  );
}

export function ChartsPanel({ m }: { m: Metrics }) {
  const heat = Object.entries(m.heatmap).map(([type, c]) => ({
    type, pass: c.pass, fail: c.fail, inconclusive: c.inconclusive,
  }));
  const frontier = m.frontier.map((f) => ({ ...f, quality: Math.round(f.quality * 100) }));

  return (
    <Box data-testid="charts">
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" }, gap: 1.5, mb: 2.5 }}>
        <Tile v={`${m.summary.certified}/${m.summary.shots_total}`} k="shots certified" />
        <Tile v={m.cost_per_passing_second == null ? "—" : `$${m.cost_per_passing_second.toFixed(2)}`} k="cost / passing sec" />
        <Tile v={m.transfer_rate == null ? "—" : `${Math.round(m.transfer_rate * 100)}%`} k="img→video transfer" />
        <Tile v={`${m.repair.repair_successes}/${m.repair.shots_repaired}`} k="repairs succeeded" />
      </Box>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2.5, mb: 2.5 }}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="h3" gutterBottom>Assertion pass-rate — an empirical capability map</Typography>
          {heat.length === 0 ? <Typography color="text.secondary">No verifications yet.</Typography> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={heat} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="type" width={130} tick={{ fill: tokens.muted, fontSize: 11 }} />
                <Tooltip {...tip} />
                <Bar dataKey="pass" stackId="a" fill={C.pass} />
                <Bar dataKey="fail" stackId="a" fill={C.fail} />
                <Bar dataKey="inconclusive" stackId="a" fill={C.inconclusive} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Paper>

        <Paper sx={{ p: 2 }}>
          <Typography variant="h3" gutterBottom>Cost–quality frontier (per shot)</Typography>
          {frontier.length === 0 ? <Typography color="text.secondary">No shots yet.</Typography> : (
            <ResponsiveContainer width="100%" height={240}>
              <ScatterChart margin={{ left: 0, bottom: 12 }}>
                <CartesianGrid stroke={tokens.border} />
                <XAxis type="number" dataKey="cost_seconds" name="cost" tick={{ fill: tokens.muted, fontSize: 11 }}
                  label={{ value: "cost (video s)", fill: tokens.muted, fontSize: 11, position: "insideBottom", offset: -6 }} />
                <YAxis type="number" dataKey="quality" name="quality" domain={[0, 100]}
                  tick={{ fill: tokens.muted, fontSize: 11 }} />
                <ZAxis range={[90, 90]} />
                <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={frontier}>
                  {frontier.map((f, i) => <Cell key={i} fill={f.certified ? C.pass : C.fail} />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </Paper>
      </Box>
    </Box>
  );
}
