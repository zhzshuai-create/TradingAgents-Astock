// Mirrors the --bp-* tokens in src/styles/tokens.css; media queries cannot
// read CSS variables, so JS consumers share these values.
export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const;

export type Breakpoint = keyof typeof BREAKPOINTS;
