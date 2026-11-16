// These mirror backend/app/models.py. Keep the two in sync.

export type FixStep =
  | { op: "drop_null_rows"; column: string }
  | {
      op: "fill_nulls";
      column: string;
      strategy: "mean" | "median" | "mode" | "constant";
      value?: string | null;
    }
  | { op: "drop_duplicates"; keep: "first" | "last" };

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
  title: string;
  columns: string[];
  count: number;
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
