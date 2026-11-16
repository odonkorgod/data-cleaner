import { Fragment, useMemo, useState } from "react";
import { analyze, transform } from "./api";
import {
  cutoffProblem,
  initialCutoffs,
  ordinal,
  outlierStep,
  resolveCutoffs,
  shareOutside,
} from "./cutoffs";
import type {
  AnalyzeResponse,
  CaseStyle,
  Category,
  Choice,
  CutoffChoice,
  CutoffMethod,
  FixStep,
  Issue,
  OutlierCutoffs,
  ReviewChoice,
  ValueReview,
} from "./types";

/** The groups issues are summarised under, in display order. */
const CATEGORIES: { id: Category; label: string; hint: string; unit: string }[] = [
  { id: "missingness", label: "Missingness", hint: "Empty cells.", unit: "cell" },
  {
    id: "inconsistent",
    label: "Inconsistent data",
    hint: "The same value written differently: case, spacing, punctuation or typos.",
    unit: "cell",
  },
  {
    id: "outliers",
    label: "Outliers",
    hint: "Numbers far outside the column's usual range.",
    unit: "cell",
  },
  {
    id: "type_mismatch",
    label: "Data type mismatch",
    hint: "Text in columns that otherwise hold numbers.",
    unit: "cell",
  },
  {
    id: "duplicates",
    label: "Duplicate rows",
    hint: "Rows that exactly repeat another row.",
    unit: "extra row",
  },
];

function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

function percent(count: number, rows: number): string {
  if (rows === 0) return "";
  const p = (count / rows) * 100;
  return p < 1 ? "(<1%)" : `(${Math.round(p)}%)`;
}

function buildSteps(issues: Issue[], choices: Record<string, Choice>): FixStep[] {
  const steps: FixStep[] = [];
  for (const issue of issues) {
    const choice = choices[issue.id];
    const fix = issue.fixes.find((f) => f.id === choice?.fixId);
    if (!fix || !fix.step) continue; // "leave as is"
    if (fix.step.op === "fill_nulls" && fix.needs_value) {
      steps.push({ ...fix.step, value: choice.value });
    } else if (fix.step.op === "standardize_values" && choice.review) {
      steps.push({ ...fix.step, case: choice.review.case, merge: choice.review.merge });
    } else if (fix.step.op === "fix_outliers" && choice.cutoffs) {
      steps.push(outlierStep(fix.step, choice.cutoffs));
    } else {
      steps.push(fix.step);
    }
  }
  return steps;
}

const CASE_LABELS: Record<CaseStyle, string> = {
  title: "Title Case",
  upper: "UPPERCASE",
  lower: "lowercase",
  keep: "As written (most common spelling)",
};

/** The starting point for a review: the column's own case style and our suggested merges. */
function initialReview(review: ValueReview): ReviewChoice {
  const merge: Record<string, string> = {};
  for (const v of review.values) if (v.suggestion) merge[v.key] = v.suggestion;
  return { case: review.case, merge };
}

/** A fresh choice for an issue: "leave as is", with any review or cut-offs at their start. */
function initialChoice(issue: Issue): Choice {
  return {
    fixId: "leave",
    value: "",
    ...(issue.review ? { review: initialReview(issue.review) } : {}),
    ...(issue.cutoffs ? { cutoffs: initialCutoffs(issue.cutoffs) } : {}),
  };
}

function formatNumber(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** "23 to 64", "from 23", "up to 64". */
function rangeText(lower: number | null, upper: number | null): string {
  if (lower !== null && upper !== null) return `${formatNumber(lower)} to ${formatNumber(upper)}`;
  return lower !== null ? `from ${formatNumber(lower)}` : `up to ${formatNumber(upper ?? 0)}`;
}

const METHOD_LABELS: Record<CutoffMethod, string> = {
  usual: "Usual range",
  percentile: "Percentiles",
  own: "My own values",
};

// Above this share of values, changing them deserves a second look.
const WARN_SHARE = 0.1;

function CutoffPanel({
  issue,
  info,
  choice,
  onChange,
}: {
  issue: Issue;
  info: OutlierCutoffs;
  choice: Choice;
  onChange: (next: CutoffChoice) => void;
}) {
  const cut = choice.cutoffs!;
  const problem = cutoffProblem(cut);
  const range = problem ? null : resolveCutoffs(info, cut);
  const pct = cut.method === "percentile";

  // The usual range's count is exact; anything else is estimated from the quantiles.
  const exact = cut.method === "usual";
  const share = range
    ? exact
      ? issue.count / info.values
      : shareOutside(info, range.lower, range.upper)
    : 0;
  const amount = exact
    ? `${issue.count.toLocaleString()} value${issue.count === 1 ? "" : "s"}`
    : share === 0
      ? "no values"
      : share < 0.01
        ? "<1% of values"
        : `≈ ${Math.round(share * 100)}% of values`;
  const verb = choice.fixId === "cap" ? "Caps" : choice.fixId === "drop_rows" ? "Drops" : "Affects";
  const preview = `${verb} ${amount}`;

  // "usual range, 23 to 64" / "1st to 99th percentile (≈ 21 to 68)" / "up to the 99th
  // percentile (≈ 68)" / "my own values, from 0".
  let summary = "Cut-offs";
  if (range && pct) {
    const lowerPct = cut.lowerPct.trim() ? ordinal(Number(cut.lowerPct)) : null;
    const upperPct = cut.upperPct.trim() ? ordinal(Number(cut.upperPct)) : null;
    const which =
      lowerPct && upperPct
        ? `${lowerPct}–${upperPct} percentile`
        : lowerPct
          ? `from the ${lowerPct} percentile`
          : `up to the ${upperPct} percentile`;
    const values =
      range.lower !== null && range.upper !== null
        ? rangeText(range.lower, range.upper)
        : formatNumber((range.lower ?? range.upper)!);
    summary = `Cut-offs: ${which} (≈ ${values})`;
  } else if (range) {
    const usual = cut.method === "usual" ? " (usual range)" : "";
    summary = `Cut-offs: ${rangeText(range.lower, range.upper)}${usual}`;
  }

  const set = (patch: Partial<CutoffChoice>) => onChange({ ...cut, ...patch });
  const labelFor = (side: string) => `${side}${pct ? " %" : ""}`;

  return (
    <details className="review">
      <summary>{summary}</summary>
      <label className="case-picker">
        <select
          aria-label="How to set the cut-offs"
          value={cut.method}
          onChange={(e) => set({ method: e.target.value as CutoffMethod })}
        >
          <option value="usual">{METHOD_LABELS.usual}</option>
          <option value="percentile" disabled={!info.percentiles_ok}>
            {METHOD_LABELS.percentile}
            {info.percentiles_ok ? "" : " (needs 100+ values)"}
          </option>
          <option value="own">{METHOD_LABELS.own}</option>
        </select>
      </label>
      {cut.method !== "usual" && (
        <>
          <div className="cutoff-inputs">
            <label>
              {labelFor("Lower")}
              <input
                type="text"
                inputMode="decimal"
                placeholder="No limit"
                value={pct ? cut.lowerPct : cut.lower}
                onChange={(e) => set(pct ? { lowerPct: e.target.value } : { lower: e.target.value })}
              />
            </label>
            <label>
              {labelFor("Upper")}
              <input
                type="text"
                inputMode="decimal"
                placeholder="No limit"
                value={pct ? cut.upperPct : cut.upper}
                onChange={(e) => set(pct ? { upperPct: e.target.value } : { upper: e.target.value })}
              />
            </label>
          </div>
        </>
      )}
      {problem ? (
        <p className="error note">{problem}</p>
      ) : (
        <p className="note">{preview}</p>
      )}
      {!problem && share > WARN_SHARE && (
        <p className="warn note">That changes a lot of values. Check the cut-offs.</p>
      )}
    </details>
  );
}

function ReviewPanel({
  review,
  choice,
  onChange,
}: {
  review: ValueReview;
  choice: ReviewChoice;
  onChange: (next: ReviewChoice) => void;
}) {
  const byKey = new Map(review.values.map((v) => [v.key, v]));
  const shown = (key: string) => byKey.get(key)?.display[choice.case] ?? key;
  const merged = Object.keys(choice.merge).length;

  function mergeInto(key: string, target: string) {
    const merge = { ...choice.merge };
    if (target === "") {
      delete merge[key];
    } else {
      merge[key] = target;
      // Anything merged into this value follows it, so merges never chain.
      for (const [k, t] of Object.entries(merge)) if (t === key) merge[k] = target;
    }
    onChange({ ...choice, merge });
  }

  return (
    <details className="review">
      <summary>
        Review {review.values.length} values{merged > 0 ? ` · ${merged} merged` : ""}
      </summary>
      <label className="case-picker">
        Write values in
        <select
          value={choice.case}
          onChange={(e) => onChange({ ...choice, case: e.target.value as CaseStyle })}
        >
          {(Object.keys(CASE_LABELS) as CaseStyle[]).map((c) => (
            <option key={c} value={c}>
              {CASE_LABELS[c]}
              {c === review.case ? " (most common)" : ""}
            </option>
          ))}
        </select>
      </label>
      <div className="table-wrap review-list">
        <table className="values">
          <thead>
            <tr>
              <th>Value</th>
              <th>Rows</th>
              <th>Merge into</th>
            </tr>
          </thead>
          <tbody>
            {review.values.map((v) => {
              const target = choice.merge[v.key] ?? "";
              return (
                <tr key={v.key} className={target ? "merged" : undefined}>
                  <td className="value">{v.display[choice.case]}</td>
                  <td className="rows">{v.count.toLocaleString()}</td>
                  <td>
                    <select
                      aria-label={`Merge ${v.display[choice.case]} into`}
                      value={target}
                      onChange={(e) => mergeInto(v.key, e.target.value)}
                    >
                      <option value="">Keep as its own value</option>
                      {review.values
                        .filter((o) => o.key !== v.key && !choice.merge[o.key])
                        .map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.display[choice.case]}
                          </option>
                        ))}
                    </select>
                    {v.suggestion && (
                      <span className="suggestion">
                        Suggested: {shown(v.suggestion)} ({v.reason?.toLowerCase()})
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function SampleTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table className="samples">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td
                  key={c}
                  className={row[c] === null ? "null" : undefined}
                  title={row[c] === null ? undefined : String(row[c])}
                >
                  {row[c] === null ? "∅" : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<AnalyzeResponse | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const steps = useMemo(
    () => (report ? buildSteps(report.issues, choices) : []),
    [report, choices],
  );

  const groups = useMemo(
    () =>
      CATEGORIES.map((category) => {
        const issues = report?.issues.filter((i) => i.category === category.id) ?? [];
        const count = issues.reduce((sum, i) => sum + i.count, 0);
        return { ...category, issues, count };
      }),
    [report],
  );

  async function onFile(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setReport(null);
    setChoices({});
    setError(null);
    setBusy(true);
    try {
      const result = await analyze(f);
      setReport(result);
      // Default every issue to "leave as is" so nothing changes unless the user chooses.
      const defaults: Record<string, Choice> = {};
      for (const issue of result.issues) defaults[issue.id] = initialChoice(issue);
      setChoices(defaults);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onDownload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await transform(file, steps);
      const base = file.name.replace(/\.[^.]+$/, "");
      download(blob, `${base}_cleaned.csv`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function setChoice(issueId: string, patch: Partial<Choice>) {
    setChoices((prev) => ({ ...prev, [issueId]: { ...prev[issueId], ...patch } }));
  }

  /** Reset these issues to "leave as is", forgetting typed values and review edits. */
  function clearFixes(issues: Issue[]) {
    setChoices((prev) => {
      const next = { ...prev };
      for (const issue of issues) next[issue.id] = initialChoice(issue);
      return next;
    });
  }

  /** Editing cut-offs means the user wants them applied, so pick "cap" if nothing is chosen. */
  function setCutoffs(issue: Issue, cutoffs: CutoffChoice) {
    const current = choices[issue.id]?.fixId;
    setChoice(issue.id, { cutoffs, ...(current === "leave" ? { fixId: "cap" } : {}) });
  }

  /** Editing a review means the user wants it applied, so select the standardize fix too. */
  function setReview(issue: Issue, review: ReviewChoice) {
    const standardize = issue.fixes.find((f) => f.step?.op === "standardize_values");
    setChoice(issue.id, { review, ...(standardize ? { fixId: standardize.id } : {}) });
  }

  /** Switch every issue that has a recommendation to it. Others keep their current choice. */
  function applyRecommended(issues: Issue[]) {
    setChoices((prev) => {
      const next = { ...prev };
      for (const issue of issues) {
        const fix = issue.fixes.find((f) => f.recommended);
        if (fix) next[issue.id] = { ...prev[issue.id], fixId: fix.id };
      }
      return next;
    });
  }

  const missingValue = report?.issues.some((issue) => {
    const choice = choices[issue.id];
    const fix = issue.fixes.find((f) => f.id === choice?.fixId);
    return fix?.needs_value && choice.value.trim() === "";
  });

  // Cut-offs that can't be used block the download while their fix is selected.
  const badCutoffs = report?.issues.some((issue) => {
    const choice = choices[issue.id];
    return choice?.cutoffs && choice.fixId !== "leave" && cutoffProblem(choice.cutoffs) !== null;
  });

  return (
    <main>
      <h1>Data Cleaner</h1>
      <p className="privacy">
        Your file is processed in memory and never stored. Nothing is saved on the server.
      </p>

      <label className="upload">
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <span>{file ? file.name : "Choose a CSV file"}</span>
      </label>

      {busy && <p className="status">Working…</p>}
      {error && <p className="error">{error}</p>}

      {report && (
        <>
          <p className="summary">
            {report.rows.toLocaleString()} rows · {report.columns.length} columns ·{" "}
            {report.issues.length === 0
              ? "no issues found"
              : `${report.issues.length} issue${report.issues.length === 1 ? "" : "s"} found`}
          </p>

          <ul className="overview">
            {groups.map((g) => (
              <li key={g.id} className={g.issues.length === 0 ? "clear" : undefined}>
                {g.issues.length > 0 ? (
                  <a href={`#${g.id}`}>{g.label}</a>
                ) : (
                  <span>{g.label}</span>
                )}
                <span className="overview-count">
                  {g.issues.length === 0
                    ? "None found"
                    : g.id === "duplicates"
                      ? plural(g.count, g.unit)
                      : `${plural(g.issues.length, "column")} · ${plural(g.count, g.unit)}`}
                </span>
              </li>
            ))}
          </ul>

          {groups
            .filter((g) => g.issues.length > 0)
            .map((g) => {
              const recommendable = g.issues.filter((i) => i.fixes.some((f) => f.recommended));
              return (
                <section key={g.id} id={g.id} className="issue">
                  <h2>
                    {g.label} <span className="count">{plural(g.count, g.unit)}</span>
                  </h2>
                  <div className="intro">
                    <p className="hint">{g.hint}</p>
                    <div className="actions">
                      {recommendable.length > 0 && (
                        <button
                          className="link-button"
                          onClick={() => applyRecommended(recommendable)}
                        >
                          Use recommended fixes
                        </button>
                      )}
                      <button
                        className="link-button"
                        onClick={() => clearFixes(g.issues)}
                        disabled={!g.issues.some((i) => choices[i.id]?.fixId !== "leave")}
                        aria-label={`Clear selected fixes for ${g.label}`}
                      >
                        Clear
                      </button>
                    </div>
                  </div>

                  <div className="table-wrap">
                    <table className="fixes">
                      <colgroup>
                        <col className="col-column" />
                        <col className="col-affected" />
                        <col className="col-fix" />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>{g.id === "duplicates" ? "Rows" : "Column"}</th>
                          <th>Affected</th>
                          <th>Fix</th>
                        </tr>
                      </thead>
                      <tbody>
                        {g.issues.map((issue) => {
                          const choice = choices[issue.id];
                          const selected = issue.fixes.find((f) => f.id === choice?.fixId);
                          return (
                            <Fragment key={issue.id}>
                              <tr>
                                <td className="column">
                                  <span className="name">
                                    {g.id === "duplicates" ? "All columns" : issue.columns.join(", ")}
                                  </span>
                                  {/* Rows with a value review show the changes there instead. */}
                                  {issue.detail && !issue.review && (
                                    <span className="detail">{issue.detail}</span>
                                  )}
                                </td>
                                <td className="affected">
                                  {issue.count.toLocaleString()}{" "}
                                  <span className="muted">{percent(issue.count, report.rows)}</span>
                                </td>
                                <td>
                                  <div className="fix">
                                    <select
                                      aria-label={`Fix for ${issue.title}`}
                                      value={choice?.fixId ?? "leave"}
                                      onChange={(e) => setChoice(issue.id, { fixId: e.target.value })}
                                    >
                                      {issue.fixes.map((f) => (
                                        <option key={f.id} value={f.id}>
                                          {f.label}
                                          {f.recommended ? " (recommended)" : ""}
                                        </option>
                                      ))}
                                    </select>
                                    {selected?.needs_value && (
                                      <input
                                        type="text"
                                        aria-label={`Value to fill ${issue.columns[0]} with`}
                                        placeholder="Value to fill with"
                                        value={choice?.value ?? ""}
                                        onChange={(e) => setChoice(issue.id, { value: e.target.value })}
                                      />
                                    )}
                                  </div>
                                </td>
                              </tr>
                              {issue.cutoffs && choice?.cutoffs && (
                                <tr className="review-row">
                                  <td colSpan={3}>
                                    <CutoffPanel
                                      issue={issue}
                                      info={issue.cutoffs}
                                      choice={choice}
                                      onChange={(next) => setCutoffs(issue, next)}
                                    />
                                  </td>
                                </tr>
                              )}
                              {issue.review && choice?.review && (
                                <tr className="review-row">
                                  <td colSpan={3}>
                                    <ReviewPanel
                                      review={issue.review}
                                      choice={choice.review}
                                      onChange={(next) => setReview(issue, next)}
                                    />
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {g.id === "duplicates" && (
                    <details>
                      <summary>Show example rows</summary>
                      <SampleTable rows={g.issues[0].samples} />
                    </details>
                  )}
                </section>
              );
            })}

          <button onClick={onDownload} disabled={busy || missingValue || badCutoffs}>
            Download cleaned CSV{steps.length > 0 ? ` (${steps.length} fix${steps.length === 1 ? "" : "es"})` : ""}
          </button>
        </>
      )}
    </main>
  );
}
