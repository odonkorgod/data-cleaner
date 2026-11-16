import { useMemo, useState } from "react";
import { analyze, transform } from "./api";
import type { AnalyzeResponse, Choice, FixStep, Issue } from "./types";

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
              <td key={c} className={row[c] === null ? "null" : undefined}>
                {row[c] === null ? "∅" : String(row[c])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
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

          {report.issues.map((issue) => {
            const choice = choices[issue.id];
            const selected = issue.fixes.find((f) => f.id === choice?.fixId);
            return (
              <section key={issue.id} className="issue">
                <h2>
                  {issue.title} <span className="count">{issue.count.toLocaleString()}</span>
                </h2>
                <SampleTable rows={issue.samples} />
                <div className="fix">
                  <select
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
                      placeholder="Value to fill with"
                      value={choice?.value ?? ""}
                      onChange={(e) => setChoice(issue.id, { value: e.target.value })}
                    />
                  )}
                </div>
              </section>
            );
          })}

          <button onClick={onDownload} disabled={busy || missingValue}>
            Download cleaned CSV{steps.length > 0 ? ` (${steps.length} fix${steps.length === 1 ? "" : "es"})` : ""}
          </button>
        </>
      )}
    </main>
  );
}
