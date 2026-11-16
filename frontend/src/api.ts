import type { AnalyzeResponse, FixStep } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "/api";

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "Some of the chosen fixes are invalid.";
  } catch {
    // fall through
  }
  return `Request failed (${res.status}).`;
}

export async function analyze(file: File): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/analyze`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function transform(file: File, steps: FixStep[]): Promise<Blob> {
  const form = new FormData();
  form.append("file", file);
  form.append("steps", JSON.stringify(steps));
  const res = await fetch(`${BASE}/transform`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.blob();
}
