import { useCallback, useEffect, useRef, useState } from "react";
import { createProject, getPacks, getProject, review, sendVerdict } from "./api";
import { ChartsPanel } from "./charts";
import { ConformanceBoard, FinalCut, NewProject, Pipeline, ReviewBar, WalletMeter } from "./components";
import type { Pack, Project } from "./types";

export default function App() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => { getPacks().then((r) => setPacks(r.packs)).catch(() => {}); }, []);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const poll = useCallback(async (id: string) => {
    try {
      const p = await getProject(id);
      setProject(p);
      if (p.status === "done" || p.status === "failed") {
        if (timer.current) { clearInterval(timer.current); timer.current = null; }
        setBusy(false);
      }
    } catch { /* transient — keep polling */ }
  }, []);

  const startPolling = useCallback((id: string) => {
    if (timer.current) clearInterval(timer.current);
    poll(id);
    timer.current = window.setInterval(() => poll(id), 2500);  // state.md: SPA polls every 2.5s
  }, [poll]);

  const onCreate = async (premise: string, pack: string, maxShots: number) => {
    setBusy(true); setErr(null); setProject(null);
    try {
      const { id } = await createProject(premise, pack, maxShots);
      setProjectId(id);
      startPolling(id);
    } catch (e) { setErr(String(e)); setBusy(false); }
  };

  const onApprove = async () => { if (projectId) { await review(projectId); poll(projectId); } };
  const onVerdict = async (shotIndex: number, type: string, verdict: string) => {
    if (projectId) { await sendVerdict(projectId, shotIndex, type, verdict); poll(projectId); }
  };
  const onReset = () => {
    if (timer.current) { clearInterval(timer.current); timer.current = null; }
    setProject(null); setProjectId(null); setBusy(false); setErr(null);
  };

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <span className="logo" onClick={onReset} style={{ cursor: "pointer" }}>◉ Dailies</span>
          <span className="tag">CI for generated video</span>
        </div>
        {project && <WalletMeter w={project.wallet} />}
      </div>

      {err && <div className="panel" style={{ borderColor: "var(--fail)" }} data-testid="error">{err}</div>}

      {!project && <NewProject packs={packs} busy={busy} onCreate={onCreate} />}

      {project && (
        <>
          <Pipeline status={project.status} />
          {project.status === "awaiting_review" && <ReviewBar onApprove={onApprove} />}
          {project.error && <div className="panel" style={{ borderColor: "var(--fail)" }}>{project.error}</div>}
          <ChartsPanel m={project.metrics} />
          <ConformanceBoard project={project} onVerdict={onVerdict} />
          <FinalCut project={project} />
          <div style={{ marginTop: 20 }}>
            <button className="btn secondary" data-testid="newrun" onClick={onReset}>New run</button>
          </div>
        </>
      )}
    </div>
  );
}
