// These mirror backend/app/models.py. Keep the two in sync.

export type FixStep =
  | { op: "standardize_values"; column: string }
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
}
