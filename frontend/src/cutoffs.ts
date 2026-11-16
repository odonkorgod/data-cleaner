// Outlier cut-offs: validating what the user typed, building the fix step, and previewing it.
//
// Previews are estimates from `quantiles` (the value at every half percentile), so they need no
// round trip to the server. The server works out percentile cut-offs exactly when it applies
// the fix, so the preview is marked "about" where it is estimated.

import type { CutoffChoice, FixStep, OutlierCutoffs } from "./types";

type OutlierStep = Extract<FixStep, { op: "fix_outliers" }>;

/** Start from the usual range, with the other inputs filled in with suggested values. */
export function initialCutoffs(c: OutlierCutoffs): CutoffChoice {
  return {
    method: "usual",
    lowerPct: String(c.lower_pct),
    upperPct: String(c.upper_pct),
    lower: c.lower_text,
    upper: c.upper_text,
  };
}

/** An empty box means no limit (null); anything else must be a number (NaN if not). */
function parse(text: string): number | null {
  const t = text.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

function typed(choice: CutoffChoice): [number | null, number | null] {
  return choice.method === "percentile"
    ? [parse(choice.lowerPct), parse(choice.upperPct)]
    : [parse(choice.lower), parse(choice.upper)];
}

/** What's wrong with the typed cut-offs, or null if they can be used. */
export function cutoffProblem(choice: CutoffChoice): string | null {
  if (choice.method === "usual") return null;
  const [lower, upper] = typed(choice);
  if (Number.isNaN(lower) || Number.isNaN(upper)) return "Cut-offs must be numbers.";
  if (lower === null && upper === null) return "Enter at least one cut-off.";
  if (choice.method === "percentile") {
    if (lower !== null && (lower < 0 || lower > 50))
      return "The lower percentile must be between 0 and 50.";
    if (upper !== null && (upper < 50 || upper > 100))
      return "The upper percentile must be between 50 and 100.";
  } else if (lower !== null && upper !== null && lower > upper) {
    return "The lower cut-off must not be above the upper one.";
  }
  return null;
}

/** The step to send. Only call when `cutoffProblem` is null. */
export function outlierStep(step: OutlierStep, choice: CutoffChoice): OutlierStep {
  if (choice.method === "usual") return step;
  const [lower, upper] = typed(choice);
  const base = { op: "fix_outliers" as const, column: step.column, action: step.action };
  return choice.method === "percentile"
    ? { ...base, lower_pct: lower, upper_pct: upper }
    : { ...base, lower, upper };
}

/** The values the cut-offs come to (percentiles estimated from the grid). */
export function resolveCutoffs(
  c: OutlierCutoffs,
  choice: CutoffChoice,
): { lower: number | null; upper: number | null } {
  if (choice.method === "usual") return { lower: c.lower, upper: c.upper };
  const [lower, upper] = typed(choice);
  if (choice.method === "own") return { lower, upper };
  const at = (pct: number) => c.quantiles[Math.round(pct * 2)];
  return { lower: lower === null ? null : at(lower), upper: upper === null ? null : at(upper) };
}

/** Estimated share of values outside the cut-offs, to the nearest half percent. */
export function shareOutside(
  c: OutlierCutoffs,
  lower: number | null,
  upper: number | null,
): number {
  let outside = 0;
  for (const q of c.quantiles) {
    if ((lower !== null && q < lower) || (upper !== null && q > upper)) outside += 1;
  }
  return Math.min(1, outside / (c.quantiles.length - 1));
}

/** 1 -> "1st", 99 -> "99th", 2.5 -> "2.5th". */
export function ordinal(n: number): string {
  if (!Number.isInteger(n) || (n % 100 >= 11 && n % 100 <= 13)) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}
