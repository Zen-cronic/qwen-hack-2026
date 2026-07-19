/** The pipeline as a live node graph — the hero surface of a run.
 *
 * Read-only: nodes and edges are derived from the polled Project each render, so the
 * canvas animates as the real pipeline advances. The controlled useNodesState/useEdgesState
 * pattern lets React Flow keep measuring node sizes (needed for edge routing) while we
 * replace the derived data on every 2.5s poll.
 */
import { useEffect, useMemo } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  Background, BackgroundVariant, Controls, ReactFlow,
  useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { deriveEdges, deriveNodes } from "./graph";
import { nodeTypes } from "./nodes";
import { mono, tokens } from "./theme";
import type { Project } from "./types";

const LEGEND: { label: string; color: string }[] = [
  { label: "active", color: tokens.accent },
  { label: "passed", color: tokens.pass },
  { label: "failed", color: tokens.fail },
  { label: "pending", color: tokens.pending },
];

export function PipelineGraph({ project, stagger = false }: { project: Project; stagger?: boolean }) {
  // stagger tags each node with a per-index entry delay for the agent-authored reveal;
  // a live run passes no stagger, so nodes just update in place on each poll.
  const derivedNodes = useMemo(() => {
    const ns = deriveNodes(project);
    return stagger ? ns.map((n, i) => ({ ...n, data: { ...n.data, enterDelay: i * 90 } })) : ns;
  }, [project, stagger]);

  const [nodes, setNodes, onNodesChange] = useNodesState(derivedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(deriveEdges(project));

  // Re-derive on each new snapshot. Positions are fixed, so this refreshes status/thumbs
  // in place without moving the graph.
  useEffect(() => { setNodes(derivedNodes); }, [derivedNodes, setNodes]);
  useEffect(() => { setEdges(deriveEdges(project)); }, [project, setEdges]);

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
