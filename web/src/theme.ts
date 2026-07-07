import { createTheme } from "@mui/material/styles";

// The Dailies "cutting-room" design system, ported from the original CSS custom
// properties into an MUI v9 theme. `tokens` is the single source of truth for the
// palette; the ones MUI's standard palette can't hold (panel2, tier colors) are
// exported for use in sx and in Recharts, which needs literal hex, not CSS vars.
export const tokens = {
  bg: "#0e1116",
  panel: "#161b22",
  panel2: "#1c2230",
  border: "#2a3240",
  text: "#e6edf3",
  muted: "#8b98a9",
  accent: "#4a9eff",
  pass: "#3fb950",
  fail: "#f85149",
  inconclusive: "#d29922",
  pending: "#6e7681",
  draft: "#a371f7",
  final: "#f0a500",
} as const;

// Measurements read as a test report — the one deliberate risk. Metric values,
// assertion details and take labels use this; prose stays sans.
export const mono = 'ui-monospace, SFMono-Regular, Menlo, "Cascadia Code", monospace';
const sans = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

// One place that maps an assertion/badge status to its hex, used by dots, chips
// and Recharts cells so a status is the same color everywhere.
export const statusColor = (s: string): string =>
  s === "pass" || s === "certified"
    ? tokens.pass
    : s === "fail" || s === "failed"
      ? tokens.fail
      : s === "inconclusive"
        ? tokens.inconclusive
        : s === "working"
          ? tokens.accent
          : tokens.pending;

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "data-theme" },
  colorSchemes: {
    dark: {
      palette: {
        mode: "dark",
        primary: { main: tokens.accent, contrastText: "#06121f" },
        success: { main: tokens.pass, contrastText: "#052e12" },
        error: { main: tokens.fail, contrastText: "#2a0808" },
        warning: { main: tokens.inconclusive, contrastText: "#241a02" },
        background: { default: tokens.bg, paper: tokens.panel },
        text: { primary: tokens.text, secondary: tokens.muted },
        divider: tokens.border,
      },
    },
  },
  defaultColorScheme: "dark",
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: sans,
    h1: { fontWeight: 750, letterSpacing: "-0.02em" },
    h2: { fontSize: "0.94rem", fontWeight: 650 },
    h3: { fontSize: "0.82rem", fontWeight: 600, color: tokens.muted },
    button: { textTransform: "none", fontWeight: 650 },
    overline: { fontSize: 11, letterSpacing: "0.04em", fontWeight: 600, lineHeight: 1.4 },
  },
  components: {
    // Flat, bordered surfaces — no Material elevation overlay or drop shadow.
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: { backgroundImage: "none", border: `1px solid ${tokens.border}` },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true, variant: "contained" },
      styleOverrides: { root: { borderRadius: 8, padding: "9px 18px" } },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 999, fontWeight: 650 },
        label: { paddingLeft: 8, paddingRight: 8 },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { backgroundColor: tokens.panel2, borderRadius: 8 },
      },
    },
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: tokens.bg },
        "*:focus-visible": { outline: `2px solid ${tokens.accent}`, outlineOffset: 2 },
        "@media (prefers-reduced-motion: reduce)": {
          "*": { animationDuration: "0.01ms !important", transitionDuration: "0.01ms !important" },
        },
      },
    },
  },
});
