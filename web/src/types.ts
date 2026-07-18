export type Status = "pending" | "pass" | "fail" | "inconclusive";

export interface AssertionResult {
  type: string;
  tier: string;
  advisory: boolean;
  status: Status;
  detail: string;
  measured: Record<string, unknown>;
  evidence: string[];
}

export interface Take {
  take_no: number;
  tier: string;
  model: string;
  prompt: string;
  status: string;
  video_path: string | null;
  results: AssertionResult[];
  passed: boolean | null;
}

export interface ShotState {
  spec: { index: number; prompt: string; subject?: string | null; assertions: unknown[] };
  status: string;
  still_path: string | null;
  tier0_results: AssertionResult[];
  takes: Take[];
  certified: boolean;
  final_path: string | null;
}

export interface Wallet {
  draft_clips: number;
  final_clips: number;
  images: number;
  tokens_in: number;
  tokens_out: number;
  video_seconds: number;
  est_usd: number;
}

export interface HeatCell {
  pass: number;
  fail: number;
  inconclusive: number;
  total: number;
  pass_rate: number;
}

export interface Metrics {
  summary: { shots_total: number; certified: number; failed: number };
  heatmap: Record<string, HeatCell>;
  frontier: {
    shot: number;
    cost_seconds: number;       // billed by THIS run (0 on cache replays)
    cost_usd: number;
    production_seconds: number; // billed + cache-replayed — what the shot cost to produce
    production_usd: number;
    replayed: boolean;
    quality: number;
    certified: boolean;
  }[];
  convergence: { shot: number; take: number; tier: string; passed: boolean; quality: number }[];
  repair: { retakes_total: number; shots_repaired: number; repair_successes: number };
  cost_per_passing_second: number | null;
  transfer_rate: number | null;
}

export interface Project {
  id: string;
  premise: string;
  pack: string;
  max_shots: number;
  custom_checks: string[];
  status: string;
  shots: ShotState[];
  wallet: Wallet;
  episode_path: string | null;
  error: string | null;
  metrics: Metrics;
}

export interface Pack {
  name: string;
  description: string;
  defaults: number;
}
