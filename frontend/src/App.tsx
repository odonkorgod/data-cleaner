import { useMemo, useState } from "react";
import { analyze, transform } from "./api";
import type { AnalyzeResponse, Category, Choice, FixStep, Issue } from "./types";

/** The groups issues are summarised under, in display order. */
const CATEGORIES: { id: Category; label: string; hint: string; unit: string }[] = [
  { id: "missingness", label: "Missingness", hint: "Empty cells.", unit: "cell" },
  {
    id: "inconsistent",
    label: "Inconsistent data",
    hint: "The same value written with different case or spacing.",
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
  return p < 1 ? "<1%" : `${Math.round(p)}%`;
}

function buildSteps(issues: Issue[], choices: Record<string, Choice>): FixStep[] {
  const steps: FixStep[] = [];
  for (const issue of issues) {
    const choice = choices[issue.id];
    const fix = issue.fixes.find((f) => f.id === choice?.fixId);
    if (!fix || !fix.step) continue; // "leave as is"
    if (fix.step.op === "fill_nulls" && fix.needs_value) {
      steps.push({ ...fix.step, value: choice.value });
    } else {
      steps.push(fix.step);
    }
  }
  return steps;
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
      for (const issue of result.issues) defaults[issue.id] = { fixId: "leave", value: "" };
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

  const missingValue = report?.issues.some((issue) => {
    const choice = choices[issue.id];
    const fix = issue.fixes.find((f) => f.id === choice?.fixId);
    return fix?.needs_value && choice.value.trim() === "";
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
            .map((g) => (
              <section key={g.id} id={g.id} className="issue">
                <h2>
                  {g.label} <span className="count">{plural(g.count, g.unit)}</span>
                </h2>
                <p className="hint">{g.hint}</p>

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
                          <tr key={issue.id}>
                            <td className="column">
                              <span className="name">
                                {g.id === "duplicates" ? "All columns" : issue.columns.join(", ")}
                              </span>
                              {issue.detail && <span className="detail">{issue.detail}</span>}
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
            ))}

          <button onClick={onDownload} disabled={busy || missingValue}>
            Download cleaned CSV{steps.length > 0 ? ` (${steps.length} fix${steps.length === 1 ? "" : "es"})` : ""}
          </button>
        </>
      )}
    </main>
  );
}
