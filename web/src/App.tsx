import { useCallback, useEffect, useRef, useState } from "react";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Container from "@mui/material/Container";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { alpha } from "@mui/material/styles";
import { createProject, getPacks, getProject, patchShot, review, sendVerdict } from "./api";
import { ChartsPanel } from "./charts";
import { ConformanceBoard, FinalCut, NewProject, Pipeline, ReviewBar, WalletMeter } from "./components";
import { mono, tokens } from "./theme";
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

  // Deep link (?p=<id>): reopen an existing run. Project state is a durable snapshot on
  // disk, so a finished run is worth linking to — it survives a reload, can be handed to
  // someone as a finished conformance report, and re-verifies from cache for free.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("p");
    if (!id) return;
    setProjectId(id);
    startPolling(id);
  }, [startPolling]);

  const onCreate = async (premise: string, pack: string, maxShots: number, customChecks: string[]) => {
    setBusy(true); setErr(null); setProject(null);
    try {
      const { id } = await createProject(premise, pack, maxShots, customChecks);
      setProjectId(id);
      window.history.replaceState(null, "", `?p=${id}`);
      startPolling(id);
    } catch (e) { setErr(String(e)); setBusy(false); }
  };

  const onApprove = async () => { if (projectId) { await review(projectId); poll(projectId); } };
  const onPatch = async (shotIndex: number) => {
    if (!projectId) return;
    setErr(null);
    // A patch is a real generation, so surface why it was refused or why it still
    // fails — silently re-polling would read as "the button did nothing".
    try {
      const r = await patchShot(projectId, shotIndex);
      if (!r.ok) setErr(`Shot ${shotIndex}: ${r.reason}`);
    } catch (e) { setErr(String(e)); }
    poll(projectId);
  };
  const onVerdict = async (shotIndex: number, type: string, verdict: string) => {
    if (projectId) { await sendVerdict(projectId, shotIndex, type, verdict); poll(projectId); }
  };
  const onReset = () => {
    if (timer.current) { clearInterval(timer.current); timer.current = null; }
    window.history.replaceState(null, "", window.location.pathname);
    setProject(null); setProjectId(null); setBusy(false); setErr(null);
  };

  return (
    <>
      <AppBar position="sticky" elevation={0} sx={{
        bgcolor: alpha(tokens.bg, 0.92), backdropFilter: "blur(8px)", color: "text.primary",
        border: 0, borderBottom: 1, borderColor: "divider",
      }}>
        <Toolbar sx={{ maxWidth: 1200, width: "100%", mx: "auto", px: { xs: 2, sm: 2.5 } }}>
          <Stack direction="row" spacing={1.25} sx={{ alignItems: "baseline", flexGrow: 1 }}>
            <Typography component="span" onClick={onReset}
              sx={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em", cursor: "pointer" }}>◉ Dailies</Typography>
            <Typography component="span" color="text.secondary" sx={{ fontSize: 13 }}>the neutral conformance gate for AI-generated video</Typography>
          </Stack>
          {project && <WalletMeter w={project.wallet} />}
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ pt: 3, pb: 8 }}>
        {err && <Paper data-testid="error" sx={{ p: 2, mb: 2.5, borderColor: "error.main" }}>{err}</Paper>}

        {!project && <NewProject packs={packs} busy={busy} onCreate={onCreate} />}

        {project && (
          <>
            <Pipeline status={project.status} />
            {project.status === "awaiting_review" && <ReviewBar onApprove={onApprove} shots={project.shots} />}
            {project.error && <Paper sx={{ p: 2, mb: 2.5, borderColor: "error.main" }}>{project.error}</Paper>}
            <ChartsPanel m={project.metrics} />
            <ConformanceBoard project={project} onVerdict={onVerdict} onPatch={onPatch} />
            <FinalCut project={project} />
            <Box sx={{ mt: 2.5 }}>
              <Button variant="outlined" color="inherit" data-testid="newrun" onClick={onReset}>New run</Button>
            </Box>
          </>
        )}

        <Typography component="footer" sx={{
          mt: 8, textAlign: "center", fontFamily: mono, fontSize: 11.5, color: "text.secondary",
        }}>
          qwen-plus scripting · wan2.1-turbo drafts · wan2.2-plus finals · qwen-vl-plus advisory — on Alibaba Cloud
        </Typography>
      </Container>
    </>
  );
}
