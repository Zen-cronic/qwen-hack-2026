/** The pipeline as a live, read-only node graph, re-derived from the polled Project.
 *  useNodesState/useEdgesState is required so React Flow keeps measuring node sizes. */
import { useCallback, useEffect, useMemo, useRef } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  Background, BackgroundVariant, Controls, type Node as RFNode, ReactFlow,
  useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { type DNodeData, deriveEdges, deriveNodes } from "./graph";
import { nodeTypes } from "./nodes";
import { mono, tokens } from "./theme";
import type { Project } from "./types";

const LEGEND: { label: string; color: string }[] = [
  { label: "active", color: tokens.accent },
  { label: "passed", color: tokens.pass },
  { label: "failed", color: tokens.fail },
  { label: "pending", color: tokens.pending },
];

export function PipelineGraph({ project, stagger = false, onPatch }: {
  project: Project;
  stagger?: boolean;
  onPatch?: (shotIndex: number) => Promise<void>;
}) {
  // A stable wrapper so injecting the handler never churns the memo on a parent re-render.
  const onPatchRef = useRef(onPatch);
  useEffect(() => { onPatchRef.current = onPatch; });
  const hasPatch = !!onPatch;
  const patchFn = useCallback((i: number) => onPatchRef.current?.(i) ?? Promise.resolve(), []);

  // stagger tags each node with an entry delay for the plan reveal; onPatch is injected
  // only into patchable check nodes, so only they carry the re-render affordance.
  const derivedNodes = useMemo(() => {
    const ns = deriveNodes(project);
    const wired = hasPatch
      ? ns.map((n) => (n.data.patchable ? { ...n, data: { ...n.data, onPatch: patchFn } } : n))
      : ns;
    return stagger ? wired.map((n, i) => ({ ...n, data: { ...n.data, enterDelay: i * 90 } })) : wired;
  }, [project, stagger, hasPatch, patchFn]);

  const [nodes, setNodes, onNodesChange] = useNodesState(derivedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(deriveEdges(project));

  // Re-derive on each snapshot; positions are fixed, so the graph doesn't move.
  useEffect(() => { setNodes(derivedNodes); }, [derivedNodes, setNodes]);
  useEffect(() => { setEdges(deriveEdges(project)); }, [project, setEdges]);

  // Clicking a node jumps to its detail card in the board below.
  const onNodeClick = useCallback((_: unknown, node: RFNode) => {
    const d = node.data as DNodeData;
    const sel = typeof d.shotIndex === "number" ? `#shot-card-${d.shotIndex}`
      : d.kind === "episode" ? '[data-testid="finalcut"]' : "";
    if (sel) document.querySelector(sel)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", mb: 1, flexWrap: "wrap" }}>
        <Typography variant="overline" sx={{ color: "text.secondary", letterSpacing: "0.08em" }}>
          Pipeline graph
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        {LEGEND.map((l) => (
          <Stack key={l.label} direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
            <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: l.color }} />
            <Typography sx={{ fontFamily: mono, fontSize: 10, color: "text.secondary" }}>{l.label}</Typography>
          </Stack>
        ))}
      </Stack>
      <Box data-testid="graph" sx={{
        height: "clamp(360px, 52vh, 560px)", borderRadius: "14px",
        border: `1px solid ${tokens.border}`, bgcolor: tokens.bg, overflow: "hidden",
      }}>
        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView fitViewOptions={{ padding: 0.16 }}
          minZoom={0.3} maxZoom={1.5}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
          proOptions={{ hideAttribution: false }}
          colorMode="dark"
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color={tokens.border} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </Box>
    </Box>
  );
}
