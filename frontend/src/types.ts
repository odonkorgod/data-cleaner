// These mirror backend/app/models.py. Keep the two in sync.

export type CaseStyle = "keep" | "title" | "upper" | "lower";

export type FixStep =
  | {
      op: "standardize_values";
      column: string;
      case: CaseStyle;
      /** Group key -> group key it becomes. Keys come from the issue's `review`. */
      merge: Record<string, string>;
      /** Group key -> text the user typed, written exactly as typed (no case style). */
      rename?: Record<string, string>;
    }
  | { op: "fix_type_mismatch"; column: string; action: "clear" | "drop_rows" }
  | {
      op: "fix_invalid";
      column: string;
      action: "clear" | "drop_rows";
      /** The allowed range. A missing bound means no limit on that side. */
      min?: number | null;
      max?: number | null;
    }
  | {
      op: "fix_outliers";
      column: string;
      action: "cap" | "drop_rows";
      /** Cut-offs as values, or as percentiles. A missing bound means no limit that side. */
      lower?: number | null;
      upper?: number | null;
      lower_pct?: number | null;
      upper_pct?: number | null;
    }
  | {
      op: "fill_nulls";
      column: string;
      strategy: "mean" | "median" | "mode" | "constant";
      value?: string | null;
    }
  /** Make placeholders like "N/A" or "NULL" truly empty cells (otherwise they're kept). */
  | { op: "clear_placeholders"; column: string }
  | { op: "drop_null_rows"; column: string }
  | { op: "drop_duplicates"; keep: "first" | "last" };

export type Category =
  | "missingness"
  | "inconsistent"
  | "invalid"
  | "outliers"
  | "type_mismatch"
  | "duplicates";

export interface FixOption {
  id: string;
  label: string;
  /** Step template to send to /transform. null means "leave as is". */
  step: FixStep | null;
  /** True when the user must type a value (e.g. fill with a constant). */
  needs_value: boolean;
  /** True for the option we suggest; the issue's `detail` says why. */
  recommended: boolean;
}

export interface Issue {
  id: string;
  type: string;
  category: Category;
  title: string;
  columns: string[];
  /** Affected cells (extra rows, for duplicates). */
  count: number;
  /** One short line for the summary, e.g. examples of the problem values. */
  detail: string | null;
  samples: Record<string, unknown>[];
  fixes: FixOption[];
  /** Inconsistent text columns only: the values to review. */
  review: ValueReview | null;
  /** Outlier columns only: suggested cut-offs and data to preview others. */
  cutoffs: OutlierCutoffs | null;
  /** Invalid-values issues only: the rule the values break. */
  rule: ValidityRule | null;
}

export interface ValidityRule {
  min: number | null;
  max: number | null;
  reason: string;
  /** Suggested from the column name or the data; "user" for rules added in the UI. */
  source: "name" | "data" | "user";
}

/** A number column's distribution, to preview rules the user adds. */
export interface NumberSummary {
  values: number;
  /** The value at every half percentile, 0 to 100 (201 entries). */
  quantiles: number[];
}

export interface OutlierCutoffs {
  /** The usual range: exact, and as written in the column (to prefill inputs). */
  lower: number;
  upper: number;
  lower_text: string;
  upper_text: string;
  /** Count of numbers, and the value at every half percentile 0..100 (201 entries). */
  values: number;
  quantiles: number[];
  percentiles_ok: boolean;
  lower_pct: number;
  upper_pct: number;
}

/** One distinct value of a text column (spelling variants already grouped). */
export interface ReviewValue {
  key: string;
  count: number;
  /** How the value is written under each case style. */
  display: Record<CaseStyle, string>;
  /** Key of the value we suggest merging this one into, and why. */
  suggestion: string | null;
  reason: string | null;
}

export interface ValueReview {
  /** The column's most common case style. */
  case: CaseStyle;
  /** Most common first. */
  values: ReviewValue[];
}

export interface AnalyzeResponse {
  rows: number;
  columns: string[];
  issues: Issue[];
  /** Number columns a rule can be added to (not IDs or codes), by name. */
  numbers: Record<string, NumberSummary>;
}

/** What the user has picked for one issue. */
export interface Choice {
  fixId: string;
  value: string;
  /** For issues with a review: the chosen case style and merges. */
  review?: ReviewChoice;
  /** For outlier issues: how the cut-offs are set. Inputs are kept as typed. */
  cutoffs?: CutoffChoice;
  /** For invalid-values issues: the allowed range, as typed. */
  rule?: RuleChoice;
}

export interface RuleChoice {
  min: string;
  max: string;
}

export type CutoffMethod = "usual" | "percentile" | "own";

export interface CutoffChoice {
  method: CutoffMethod;
  lowerPct: string;
  upperPct: string;
  lower: string;
  upper: string;
}

export interface ReviewChoice {
  case: CaseStyle;
  merge: Record<string, string>;
  /** Values the user typed their own text for, as typed. A key is never also in `merge`. */
  rename: Record<string, string>;
}
