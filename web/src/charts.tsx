import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import type { Metrics } from "./types";

const C = { pass: "#3fb950", fail: "#f85149", inconclusive: "#d29922" };
const tip = {
  contentStyle: { background: "#161b22", border: "1px solid #2a3240", borderRadius: 8, color: "#e6edf3" },
  labelStyle: { color: "#8b98a9" },
};

function Tile({ v, k }: { v: string; k: string }) {
  return (
    <div className="tile">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

export function ChartsPanel({ m }: { m: Metrics }) {
  const heat = Object.entries(m.heatmap).map(([type, c]) => ({
    type, pass: c.pass, fail: c.fail, inconclusive: c.inconclusive,
  }));
  const frontier = m.frontier.map((f) => ({ ...f, quality: Math.round(f.quality * 100) }));

  return (
    <div data-testid="charts">
      <div className="tiles">
        <Tile v={`${m.summary.certified}/${m.summary.shots_total}`} k="shots certified" />
        <Tile v={m.cost_per_passing_second == null ? "—" : `$${m.cost_per_passing_second.toFixed(2)}`} k="cost / passing sec" />
        <Tile v={m.transfer_rate == null ? "—" : `${Math.round(m.transfer_rate * 100)}%`} k="img→video transfer" />
        <Tile v={`${m.repair.repair_successes}/${m.repair.shots_repaired}`} k="repairs succeeded" />
      </div>
      <div className="charts-grid">
        <div className="chart-card">
          <h3>Assertion pass-rate — an empirical capability map</h3>
          {heat.length === 0 ? <p className="muted">No verifications yet.</p> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={heat} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="type" width={130} tick={{ fill: "#8b98a9", fontSize: 11 }} />
                <Tooltip {...tip} />
                <Bar dataKey="pass" stackId="a" fill={C.pass} />
                <Bar dataKey="fail" stackId="a" fill={C.fail} />
                <Bar dataKey="inconclusive" stackId="a" fill={C.inconclusive} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="chart-card">
          <h3>Cost–quality frontier (per shot)</h3>
          {frontier.length === 0 ? <p className="muted">No shots yet.</p> : (
            <ResponsiveContainer width="100%" height={240}>
              <ScatterChart margin={{ left: 0, bottom: 12 }}>
                <CartesianGrid stroke="#2a3240" />
                <XAxis type="number" dataKey="cost_seconds" name="cost" tick={{ fill: "#8b98a9", fontSize: 11 }}
                  label={{ value: "cost (video s)", fill: "#8b98a9", fontSize: 11, position: "insideBottom", offset: -6 }} />
                <YAxis type="number" dataKey="quality" name="quality" domain={[0, 100]}
                  tick={{ fill: "#8b98a9", fontSize: 11 }} />
                <ZAxis range={[90, 90]} />
                <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={frontier}>
                  {frontier.map((f, i) => <Cell key={i} fill={f.certified ? C.pass : C.fail} />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}
