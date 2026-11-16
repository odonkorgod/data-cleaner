// These mirror backend/app/models.py. Keep the two in sync.

export type CaseStyle = "keep" | "title" | "upper" | "lower";

export type FixStep =
  | {
      op: "standardize_values";
      column: string;
      case: CaseStyle;
      /** Group key -> group key it becomes. Keys come from the issue's `review`. */
      merge: Record<string, string>;
    }
  | { op: "fix_type_mismatch"; column: string; action: "clear" | "drop_rows" }
  | {
      op: "fix_outliers";
      column: string;
      lower: number;
      upper: number;
      action: "cap" | "drop_rows";
    }
  | {
      op: "fill_nulls";
      column: string;
      strategy: "mean" | "median" | "mode" | "constant";
      value?: string | null;
    }
  | { op: "drop_null_rows"; column: string }
  | { op: "drop_duplicates"; keep: "first" | "last" };

export type Category =
  | "missingness"
  | "inconsistent"
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
}

/** What the user has picked for one issue. */
export interface Choice {
  fixId: string;
  value: string;
  /** For issues with a review: the chosen case style and merges. */
  review?: ReviewChoice;
}

export interface ReviewChoice {
  case: CaseStyle;
  merge: Record<string, string>;
}
