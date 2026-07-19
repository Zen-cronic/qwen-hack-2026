/** The headline surface: a request in plain language, and a Qwen agent wires the pipeline.
 *
 * The agent calls the build_pipeline_graph tool; the server expands the parameters into the
 * canonical graph and returns it with the tool-call transcript. We render that plan on the
 * same PipelineGraph the live run uses (a stub Project), with a staggered reveal, then hand
 * the parameters to the existing create flow to actually run it.
 */
import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { alpha } from "@mui/material/styles";
import { planPipeline } from "./api";
import { planStubProject } from "./graph";
import { PipelineGraph } from "./PipelineGraph";
import { mono, tokens } from "./theme";
import { packLabel } from "./vocabulary";
import type { PipelinePlan, PlanTranscriptEntry } from "./types";

const SAMPLE_REQUESTS = [
  "a 3-shot noir chase that must end on a title card",
  "a 2-shot brand promo — stay on our palette, camera pans right",
  "a lighthouse keeper finds a message in a bottle, 4 shots",
];

// Pretty-print the tool arguments for the evidence panel — the receipt that a Qwen
// custom tool, not hand-wiring, produced this pipeline.
function toolCall(t: PlanTranscriptEntry): string {
  if (!t?.name) return "";
  let args = t.arguments ?? "{}";
  try { args = JSON.stringify(JSON.parse(args), null, 2); } catch { /* leave raw */ }
  return `${t.name}(${args})`;
}

export function AgentPrompt({ busy, onCreate }: {
  busy: boolean;
  onCreate: (premise: string, pack: string, maxShots: number, customChecks: string[]) => void;
}) {
  const [message, setMessage] = useState(SAMPLE_REQUESTS[0]);
  const [plan, setPlan] = useState<PipelinePlan | null>(null);
  const [transcript, setTranscript] = useState<PlanTranscriptEntry[]>([]);
  const [thinking, setThinking] = useState(false);
  const [showTool, setShowTool] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const design = async () => {
    setThinking(true); setErr(null); setPlan(null);
    try {
      const r = await planPipeline(message);
      setPlan(r.plan);
      setTranscript(r.transcript);
    } catch (e) {
      setErr(`Couldn't reach the planner: ${String(e)}`);
    } finally {
      setThinking(false);
    }
  };

  const run = () => {
    if (plan) onCreate(plan.premise, plan.pack, plan.max_shots, plan.custom_checks);
  };

  return (
    <Box sx={{ pt: { xs: 4, sm: 7 }, pb: 3 }}>
      <Box sx={{ maxWidth: 860, mx: "auto" }}>
        <Typography variant="overline" sx={{ color: tokens.accent, letterSpacing: "0.1em", display: "block", textAlign: "center", mb: 1 }}>
          Agent-directed pipeline
        </Typography>
        <Typography variant="h1" sx={{
          fontSize: "clamp(2rem, 4.5vw, 3.1rem)", letterSpacing: "-0.03em",
          lineHeight: 1.08, textAlign: "center", mb: 2,
        }}>
          Describe it. The agent wires the{" "}
          <Box component="span" sx={{ color: tokens.accent }}>pipeline</Box>.
        </Typography>
        <Typography color="text.secondary" sx={{ textAlign: "center", maxWidth: 620, mx: "auto", mb: 4 }}>
          A Qwen agent turns your request into a Dailies pipeline — shot list, deterministic
          CV and VLM checks, a human review gate, and a certified cut — as a live graph you
          can watch run.
        </Typography>

        <Paper sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: "16px" }}>
          <TextField
            variant="standard" multiline minRows={2} fullWidth
            value={message} onChange={(e) => setMessage(e.target.value)}
            placeholder="Describe the episode you want…"
            slotProps={{
              input: { disableUnderline: true, sx: { fontSize: 17, lineHeight: 1.45, px: 0.5, py: 0.5 } },
              htmlInput: { "data-testid": "agent-prompt", "aria-label": "Pipeline request" },
            }}
          />
          <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", mt: 1.5, pt: 1.5, borderTop: 1, borderColor: "divider" }}>
            <Typography sx={{ fontFamily: mono, fontSize: 11, color: "text.secondary", flexGrow: 1 }}>
              qwen-plus · build_pipeline_graph
            </Typography>
            <Button disabled={thinking || busy || !message.trim()} data-testid="agent-design" onClick={design}>
              {thinking ? "Wiring the graph…" : "Design pipeline"}
            </Button>
          </Stack>
        </Paper>

        <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: "wrap", justifyContent: "center", mt: 2.5 }}>
          {SAMPLE_REQUESTS.map((s) => (
            <Chip key={s} size="small" variant="outlined" label={s} onClick={() => setMessage(s)}
              sx={{ maxWidth: "100%", height: "auto", py: 0.4, color: "text.secondary", "& .MuiChip-label": { whiteSpace: "normal" } }} />
          ))}
        </Stack>

        {err && (
          <Typography data-testid="agent-error" sx={{ mt: 2, textAlign: "center", color: "error.main", fontSize: 13 }}>
            {err}
          </Typography>
        )}
      </Box>

      <Collapse in={!!plan} timeout={300}>
        {plan && (
          <Box sx={{ maxWidth: 1080, mx: "auto", mt: 4 }}>
            <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", flexWrap: "wrap", mb: 1.5 }}>
              <Chip size="small" label={`${plan.max_shots} shots`} sx={{ bgcolor: alpha(tokens.accent, 0.16), color: tokens.accent, border: `1px solid ${alpha(tokens.accent, 0.4)}` }} />
              <Chip size="small" label={packLabel(plan.pack)} variant="outlined" />
              {plan.custom_checks.map((c) => (
                <Chip key={c} size="small" variant="outlined" label={c}
                  sx={{ color: "text.secondary", maxWidth: 340, "& .MuiChip-label": { whiteSpace: "normal" } }} />
              ))}
              <Box sx={{ flexGrow: 1 }} />
              <Button variant="text" color="inherit" size="small" onClick={() => setShowTool((v) => !v)}
                sx={{ color: "text.secondary", fontFamily: mono, fontSize: 11 }}>
                {showTool ? "hide tool call ▴" : "tool call ▾"}
              </Button>
            </Stack>

            {plan.rationale && (
              <Typography sx={{ fontFamily: mono, fontSize: 12.5, color: "text.secondary", mb: 1.5 }}>
                {plan.rationale}
              </Typography>
            )}

            <Collapse in={showTool}>
              <Box component="pre" data-testid="agent-transcript" sx={{
                fontFamily: mono, fontSize: 11, color: "text.secondary", bgcolor: tokens.panel2,
                border: `1px solid ${tokens.border}`, borderRadius: "8px", p: 1.5, mb: 2,
                overflowX: "auto", whiteSpace: "pre-wrap",
              }}>
                {transcript.map(toolCall).filter(Boolean).join("\n\n")}
              </Box>
            </Collapse>

            <PipelineGraph project={planStubProject(plan)} stagger />

            <Stack direction="row" spacing={1.5} sx={{ mt: 1.5, justifyContent: "center", alignItems: "center" }}>
              <Button size="large" data-testid="agent-run" disabled={busy} onClick={run} sx={{ px: 4 }}>
                {busy ? "Starting…" : "Run this pipeline"}
              </Button>
              <Button variant="text" color="inherit" onClick={() => setPlan(null)} sx={{ color: "text.secondary" }}>
                Start over
              </Button>
            </Stack>
          </Box>
        )}
      </Collapse>
    </Box>
  );
}
