import { useState } from "react";
import { mediaUrl } from "./api";
import type { AssertionResult, Pack, Project, ShotState, Take, Wallet } from "./types";

const STAGES = ["queued", "scripting", "tier0", "awaiting_review", "drafting",
  "verifying", "repairing", "promoting", "assembling", "done"];

export function WalletMeter({ w, judge }: { w: Wallet; judge?: { judge_mode: boolean } }) {
  const cell = (v: string | number, k: string) => (
    <div className="cell"><div className="v">{v}</div><div className="k">{k}</div></div>
  );
  return (
    <div className="wallet" data-testid="wallet">
      {cell(w.draft_clips, "drafts")}
      {cell(w.final_clips, "finals")}
      {cell(w.images, "stills")}
      {cell((w.tokens_in + w.tokens_out).toLocaleString(), "tokens")}
      {cell(`$${w.est_usd.toFixed(2)}`, "est. cost")}
      {judge?.judge_mode && <span className="judge-pill">judge mode</span>}
    </div>
  );
}

export function NewProject({ packs, busy, onCreate }: {
  packs: Pack[]; busy: boolean; onCreate: (premise: string, pack: string, maxShots: number) => void;
}) {
  const [premise, setPremise] = useState("a lonely lighthouse keeper who discovers a message in a bottle");
  const [pack, setPack] = useState("short_drama");
  const [maxShots, setMaxShots] = useState(3);
  return (
    <div className="panel">
      <h2>New run</h2>
      <div className="form-row">
        <div style={{ flex: 1 }}>
          <label>Premise</label>
          <input type="text" value={premise} onChange={(e) => setPremise(e.target.value)} data-testid="premise" />
        </div>
        <div>
          <label>Assertion pack</label>
          <select value={pack} onChange={(e) => setPack(e.target.value)} data-testid="pack">
            {packs.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.defaults})</option>)}
          </select>
        </div>
        <div>
          <label>Shots</label>
          <input type="number" min={1} max={12} value={maxShots}
            onChange={(e) => setMaxShots(Number(e.target.value))} style={{ width: 70 }} />
        </div>
        <button className="btn" disabled={busy || !premise.trim()} data-testid="create"
          onClick={() => onCreate(premise, pack, maxShots)}>
          {busy ? "Running…" : "Compile & generate"}
        </button>
      </div>
    </div>
  );
}

export function Pipeline({ status }: { status: string }) {
  const cur = STAGES.indexOf(status);
  return (
    <div className="pipeline" data-testid="pipeline">
      {STAGES.map((s, i) => {
        const cls = status === "failed" ? "" : i < cur ? "done" : i === cur ? "active" : "";
        return <span key={s} className={`stage ${cls}`}>{s}</span>;
      })}
      {status === "failed" && <span className="stage active" style={{ background: "var(--fail)" }}>failed</span>}
    </div>
  );
}

export function ReviewBar({ onApprove }: { onApprove: () => void }) {
  return (
    <div className="reviewbar" data-testid="reviewbar">
      <div className="msg">
        <strong>Review the shot list before spending video budget</strong>
        <span className="muted">Tier-0 stills are ready. This is the one human gate — approve to start drafting.</span>
      </div>
      <button className="btn" data-testid="approve" onClick={onApprove}>Approve &amp; generate</button>
    </div>
  );
}

function Check({ r, onVerdict }: { r: AssertionResult; onVerdict?: (v: string) => void }) {
  const canOverride = r.advisory && onVerdict && (r.status === "inconclusive" || r.status === "fail");
  return (
    <div className="check">
      <span className={`dot ${r.status}`} />
      <div>
        <div>
          <span className="name">{r.type}</span>
          {r.advisory && <span className="tierb">advisory</span>}
        </div>
        {r.detail && <div className="detail">{r.detail}</div>}
        {canOverride && (
          <div className="verdict-btns">
            <button onClick={() => onVerdict!("pass")}>mark pass</button>
            <button onClick={() => onVerdict!("fail")}>mark fail</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ShotCard({ shot, onVerdict }: {
  shot: ShotState;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
}) {
  const takes = shot.takes;
  const [sel, setSel] = useState<number>(-1);
  const take: Take | undefined = takes.length ? takes[sel < 0 ? takes.length - 1 : sel] : undefined;
  const results = take ? take.results : shot.tier0_results;
  const thumb = take?.results.find((r) => r.evidence.length)?.evidence[0] ?? shot.still_path;
  const badge = shot.certified ? "certified" : shot.status === "failed" ? "failed" : "working";

  return (
    <div className="shot" data-testid="shot">
      {thumb ? <img className="thumb" src={mediaUrl(thumb)} alt={`shot ${shot.spec.index}`} />
        : <div className="thumb" />}
      <div className="body">
        <div className="head">
          <div>
            <div className="idx">Shot {shot.spec.index}{shot.spec.subject ? ` · ${shot.spec.subject}` : ""}</div>
            <div className="prompt">{shot.spec.prompt}</div>
          </div>
          <span className={`badge ${badge}`} data-testid="shot-badge">{badge}</span>
        </div>

        {takes.length > 1 && (
          <div className="tabs">
            {takes.map((t, i) => {
              const active = (sel < 0 ? takes.length - 1 : sel) === i;
              return (
                <button key={i} className={`tab ${active ? "sel" : ""}`} onClick={() => setSel(i)}>
                  <div className="t">{t.tier}</div>take {t.take_no}{t.passed === false ? " ✕" : t.passed ? " ✓" : ""}
                </button>
              );
            })}
          </div>
        )}

        <div className="checks">
          {results.length === 0 && <span className="muted">No checks yet.</span>}
          {results.map((r, i) => (
            <Check key={i} r={r}
              onVerdict={(v) => onVerdict(shot.spec.index, r.type, v)} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConformanceBoard({ project, onVerdict }: {
  project: Project;
  onVerdict: (shotIndex: number, type: string, verdict: string) => void;
}) {
  return (
    <div className="panel">
      <h2>Conformance board</h2>
      <div className="board" data-testid="board">
        {project.shots.length === 0 && <p className="muted">Waiting for the script agent…</p>}
        {project.shots.map((s) => <ShotCard key={s.spec.index} shot={s} onVerdict={onVerdict} />)}
      </div>
    </div>
  );
}

export function FinalCut({ project }: { project: Project }) {
  if (!project.episode_path) return null;
  return (
    <div className="panel finalcut" data-testid="finalcut">
      <h2>Certified episode</h2>
      <video controls src={mediaUrl(project.episode_path)} />
      <p className="muted">
        {project.metrics.summary.certified}/{project.metrics.summary.shots_total} shots certified ·
        re-verifies from cache at zero video cost.
      </p>
    </div>
  );
}
