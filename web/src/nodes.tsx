/** Custom React Flow node components for the pipeline graph.
 *
 * Each node is a flat bordered card in the cutting-room palette; its accent color and
 * pulse are driven by the derived NodeStatus so the canvas reads the same way the board
 * and stepper do. Presentational only — all state comes from graph.ts.
 */
import { type MouseEvent, type ReactNode, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { alpha } from "@mui/material/styles";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import { mediaUrl } from "./api";
import { mono, statusColor, tokens } from "./theme";
import type { DNodeData, NodeStatus } from "./graph";

const NODE_W = 190;

function nodeColor(s: NodeStatus): string {
  if (s === "active") return tokens.accent;
  if (s === "done" || s === "pass") return tokens.pass;
  if (s === "failed" || s === "fail") return tokens.fail;
  if (s === "inconclusive") return tokens.inconclusive;
  return tokens.pending;
}

const STATUS_GLYPH: Record<string, string> = {
  done: "✓", pass: "✓", fail: "✕", failed: "✕", inconclusive: "!",
};

// The invisible connection points edges attach to — the graph is read-only, so they
// carry no affordance of their own.
const HANDLE_STYLE = { width: 1, height: 1, minWidth: 1, border: "none", background: "transparent", opacity: 0 } as const;

function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} style={HANDLE_STYLE} />
      <Handle type="source" position={Position.Right} isConnectable={false} style={HANDLE_STYLE} />
    </>
  );
}

function StatusDot({ status }: { status: NodeStatus }) {
  const c = nodeColor(status);
  const glyph = STATUS_GLYPH[status];
  return (
    <Box component="span" sx={{
      width: 15, height: 15, borderRadius: "50%", flex: "none",
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      fontSize: 9, lineHeight: 1, color: status === "idle" ? tokens.muted : "#0b0f14",
      bgcolor: status === "idle" ? "transparent" : c,
      border: status === "idle" ? `1px solid ${tokens.border}` : "none",
      ...(status === "active" && {
        bgcolor: "transparent", border: `2px solid ${c}`,
        animation: "dailies-node-pulse 1.6s ease-in-out infinite",
        "@keyframes dailies-node-pulse": { "0%, 100%": { opacity: 1 }, "50%": { opacity: 0.3 } },
      }),
    }}>{status === "active" ? "" : glyph}</Box>
  );
}

// Shared card chrome: border + faint fill tinted by status, header with label + dot.
function NodeShell({ data, children }: { data: DNodeData; children?: ReactNode }) {
  const c = nodeColor(data.status);
  const lit = data.status !== "idle";
  const interactive = data.shotIndex != null || data.kind === "episode";
  return (
    <Box data-testid="graph-node" sx={{
      width: NODE_W, borderRadius: "10px", bgcolor: tokens.panel2,
      border: `1px solid ${lit ? alpha(c, 0.55) : tokens.border}`,
      boxShadow: data.status === "active" ? `0 0 0 1px ${alpha(c, 0.5)}` : "none",
      overflow: "hidden", cursor: interactive ? "pointer" : "default",
      ...(data.enterDelay != null && {
        opacity: 0,
        animation: "dailies-node-enter 0.4s ease forwards",
        animationDelay: `${data.enterDelay}ms`,
        "@keyframes dailies-node-enter": {
          from: { opacity: 0, transform: "translateY(6px) scale(0.96)" },
          to: { opacity: 1, transform: "translateY(0) scale(1)" },
        },
      }),
    }}>
      <Handles />
      <Stack direction="row" spacing={0.75} sx={{ alignItems: "center", px: 1.25, pt: 1, pb: children ? 0.75 : 1 }}>
        <StatusDot status={data.status} />
        <Typography sx={{ fontSize: 13, fontWeight: 600, letterSpacing: "-0.01em", flex: 1, minWidth: 0 }}>
          {data.label}
        </Typography>
        {data.model && (
          <Typography component="span" sx={{ fontFamily: mono, fontSize: 9, color: "text.secondary", whiteSpace: "nowrap" }}>
            {data.model.replace(/^wan/, "")}
          </Typography>
        )}
      </Stack>
      {children}
    </Box>
  );
}

function Caption({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <Typography sx={{ px: 1.25, pb: 1, fontFamily: mono, fontSize: 10, color: "text.secondary", lineHeight: 1.3 }}>
      {text}
    </Typography>
  );
}

export function StageNode({ data }: NodeProps) {
  const d = data as DNodeData;
  return <NodeShell data={d}><Caption text={d.caption} /></NodeShell>;
}

export function ReviewNode({ data }: NodeProps) {
  const d = data as DNodeData;
  const amber = d.status === "active";
  return (
    <Box sx={amber ? {
      borderRadius: "12px",
      background: `linear-gradient(135deg, ${alpha(tokens.inconclusive, 0.18)}, transparent 60%)`,
      p: "2px",
    } : undefined}>
      <NodeShell data={d}>
        <Caption text={d.caption} />
      </NodeShell>
    </Box>
  );
}

export function ShotNode({ data }: NodeProps) {
  const d = data as DNodeData;
  return (
    <NodeShell data={d}>
      {d.thumb ? (
        <Box component="img" alt={d.label} src={mediaUrl(d.thumb)} sx={{
          width: "100%", aspectRatio: "16 / 9", objectFit: "cover", display: "block",
          bgcolor: "#000", borderTop: `1px solid ${tokens.border}`,
        }} />
      ) : (
        <Box sx={{
          width: "100%", aspectRatio: "16 / 9", display: "flex", alignItems: "center",
          justifyContent: "center", bgcolor: tokens.bg, borderTop: `1px solid ${tokens.border}`,
        }}>
          <Typography sx={{ fontFamily: mono, fontSize: 9, color: "text.secondary" }}>
            {d.status === "active" ? "rendering…" : "no clip yet"}
          </Typography>
        </Box>
      )}
      <Caption text={d.caption} />
    </NodeShell>
  );
}

// The one action on the read-only canvas: re-render a shot whose latest take still fails a
// blocking check, from the same second the board's patch button names. stopPropagation
// keeps the node-click (scroll-to-card) from also firing; nodrag/nopan keep React Flow
// from treating the press as a canvas pan. Patching acts on the shot, so state is local.
function PatchButton({ data }: { data: DNodeData }) {
  const [patching, setPatching] = useState(false);
  const anchor = (data.anchorS ?? 0).toFixed(1);
  const run = async (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (patching) return;
    setPatching(true);
    try { await data.onPatch!(data.shotIndex!); } finally { setPatching(false); }
  };
  return (
    <Box sx={{ px: 1.25, pb: 1 }}>
      <Button
        className="nodrag nopan" data-testid="node-patch"
        size="small" variant="outlined" color="inherit" disabled={patching} onClick={run}
        title={data.failLabel ? `not yet true: ${data.failLabel}` : undefined}
        aria-label={`Re-render shot ${data.shotIndex} from ${anchor} seconds`}
        sx={{
          fontFamily: mono, fontSize: 9.5, lineHeight: 1.4, py: 0.2, px: 0.9,
          minHeight: 0, width: "100%",
          borderColor: alpha(tokens.fail, 0.5), color: tokens.fail,
          "&:hover": { borderColor: tokens.fail, bgcolor: alpha(tokens.fail, 0.08) },
        }}
      >
        {patching ? "re-rendering…" : `⟲ re-render from ${anchor}s`}
      </Button>
    </Box>
  );
}

export function CheckNode({ data }: NodeProps) {
  const d = data as DNodeData;
  const checks = d.checks ?? [];
  const shown = checks.slice(0, 6);
  return (
    <NodeShell data={d}>
      {shown.length > 0 ? (
        <Stack direction="row" spacing={0.5} useFlexGap sx={{ flexWrap: "wrap", px: 1.25, pb: 1 }}>
          {shown.map((c, i) => (
            <Chip key={i} size="small" label={c.label} sx={{
              height: 18, fontSize: 9.5,
              bgcolor: alpha(statusColor(c.status), 0.16),
              color: statusColor(c.status),
              border: `1px solid ${alpha(statusColor(c.status), 0.4)}`,
              "& .MuiChip-label": { px: 0.75 },
            }} />
          ))}
          {checks.length > shown.length && (
            <Typography component="span" sx={{ fontFamily: mono, fontSize: 9.5, color: "text.secondary", alignSelf: "center" }}>
              +{checks.length - shown.length}
            </Typography>
          )}
        </Stack>
      ) : (
        <Caption text={d.status === "idle" ? "awaiting a take" : d.caption} />
      )}
      {d.patchable && d.onPatch && d.shotIndex != null && <PatchButton data={d} />}
    </NodeShell>
  );
}

export function EpisodeNode({ data }: NodeProps) {
  const d = data as DNodeData;
  const ready = !!d.episodePath;
  return (
    <NodeShell data={d}>
      <Box sx={{ px: 1.25, pb: 1 }}>
        <Box sx={{
          width: "100%", aspectRatio: "16 / 9", borderRadius: "6px",
          border: `1px solid ${ready ? alpha(tokens.pass, 0.5) : tokens.border}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          bgcolor: ready ? alpha(tokens.pass, 0.08) : tokens.bg,
        }}>
          <Typography sx={{ fontSize: 20, color: ready ? tokens.pass : tokens.muted }}>
            {ready ? "▶" : "▣"}
          </Typography>
        </Box>
        <Caption text={d.caption} />
      </Box>
    </NodeShell>
  );
}

export const nodeTypes = {
  stage: StageNode,
  review: ReviewNode,
  shot: ShotNode,
  check: CheckNode,
  episode: EpisodeNode,
};
