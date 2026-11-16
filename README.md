# Data Cleaner

A web app for analysts. Upload a messy CSV, review the data quality issues it finds, choose how to fix each one, and download a cleaned CSV.

**Privacy by design:** files are processed in memory and never stored. There is no database, no file storage, and no logging of file contents.

## How it works

1. `POST /analyze` receives the CSV and returns a list of issues. Each issue belongs to a category (missingness, inconsistent data, outliers, data type mismatch, duplicate rows) and has a count, a one-line detail, a few sample rows, and a menu of possible fixes. The UI shows a summary per category rather than a preview per column.
2. The user picks a fix for each issue in the browser.
3. `POST /transform` receives the same CSV again plus the chosen fixes, applies them, and returns the cleaned CSV.

The server is stateless, so the browser keeps the file between steps and re-sends it. Uploads are capped at 25 MB (set `MAX_UPLOAD_MB` to change it).

**Untouched data stays untouched.** Every cell is read as text and only empty cells count as missing, so leading zeros (`00123`), values like `NA` or `None`, and integer formatting survive. The cleaned file is written with the upload's delimiter, encoding and line endings. Numbers are only parsed where a check or fix needs them (mean, median, outliers, type mismatch). See `backend/app/csv_io.py`.

### Fix steps

Each fix is a small JSON object discriminated by `op`, validated with Pydantic (`backend/app/models.py`) and mirrored in TypeScript (`frontend/src/types.ts`):

```json
{"op": "standardize_values", "column": "city", "case": "title", "merge": {"new yrok": "new york"}}
{"op": "fix_type_mismatch", "column": "age", "action": "clear"}
{"op": "fix_outliers", "column": "age", "lower": 18, "upper": 90, "action": "cap"}
{"op": "fill_nulls", "column": "age", "strategy": "median"}
{"op": "drop_null_rows", "column": "name"}
{"op": "drop_duplicates", "keep": "first"}
```

Steps always run in a **fixed order** (the order above), not the order they were chosen. Values are fixed first (spellings, stray text, then outliers, so a mean fill isn't skewed by them), then gaps are filled or dropped, and duplicates are checked last so rows that become identical after earlier fixes are caught. See `STEP_ORDER` in `models.py`.

### Detectors

| Category | What counts | Rule |
|---|---|---|
| Missingness | Empty cells | Only truly empty cells; `NA`, `None` etc. are kept as text |
| Inconsistent data | Same value written differently | Case and spacing variants are grouped; in categories, the column's usual case style is applied and near-duplicates (typos, punctuation) are suggested as merges |
| Outliers | Numbers far from the usual range | Tukey's fences (1.5 × IQR), needs 8+ numbers; capping uses the most extreme normal value |
| Data type mismatch | Text in a number column | Column is at least 80% numbers; the rest is flagged |
| Duplicate rows | Rows that repeat exactly | Count is the extra copies a fix would remove |

Thresholds live in `backend/app/values.py` and `backend/app/categories.py`.

### Reviewing inconsistent categories

For a text column of repeating categories with at most 100 distinct values, the issue includes a `review`: each value (case and spacing variants already grouped) with its row count, how it looks in each case style, and a suggested merge where one fits. In the UI the user picks the case style and can merge any value into another; nothing is applied until they choose. Other text columns (names, free text, or more than 100 values) are only cleaned of case and spacing variants.

- **Case style:** the column's most common style by cells (Title Case, UPPERCASE or lowercase). Guards keep correct values intact: deliberate mixed case (`eBay`, `McDonald`, `O'Neil`) is never changed; in Title Case, short all-caps values (`USA`, `NASA`) and acronyms inside values (`NYC Office`) are kept, small words stay lowercase (`Bank of America`), and only the first letter of a word is capitalized (`They're`, not `They'Re`).
- **Suggested merges:** same letters with different punctuation (`N.Y.C.` → `NYC`), or typos: one edit in words of 5–8 letters, two from 9, only swapped neighbours at 4 letters, none below. The shorter word sets the allowance, so `Austria` is not a typo of `Australia`; values with different numbers (`Room 101`/`Room 102`) never match. Rare values merge into common ones, never in chains.
- **Merges** are keyed by the value's group key (trimmed, single-spaced, lowercased), so they stay valid whichever case style is chosen.

### Recommended fill for missing values

Each missing-values issue marks one fix as `recommended` and explains why in its `detail` line. The UI tags that option and offers "Use recommended fixes"; nothing is applied until the user chooses. The choice follows the kind of data (`column_kind` in `values.py`):

| Column holds | Example | Recommended |
|---|---|---|
| Roughly normal numbers (\|skewness\| ≤ 0.5 and \|excess kurtosis\| ≤ 1, 20+ values) | heights | Mean |
| Other numbers (skewed, heavy- or light-tailed, or too few to judge) | incomes | Median |
| An ordinal scale: whole numbers spanning ≤ 10 steps that repeat | satisfaction 1–10, Likert 1–5, 0/1 flags | Mode |
| Text categories that repeat (≤ 50% distinct) | city, plan tier | Mode |
| IDs or free text (values rarely repeat) | `customer_id`, notes | Leave as is |

Normality is judged by effect size (skewness, kurtosis), not a significance test, which on large files rejects normality over differences too small to matter. The thresholds are deliberately strict because recommending the median for normal data costs little, while recommending the mean for skewed data is the mistake worth avoiding.

## Project layout

```
backend/            FastAPI + pandas
  app/
    main.py         endpoints
    models.py       issue and fix-step schemas
    csv_io.py       encoding/delimiter detection, CSV in and out
    values.py       number parsing, outlier range, column kinds (shared by detectors and fixes)
    categories.py   text categories: case styles, grouping, merge suggestions
    detectors/      one module per issue type, registered in detectors/__init__.py
    transform.py    applies fix steps in fixed order
  tests/
frontend/           React + TypeScript (Vite)
```

## Running locally

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node 20+.

```bash
# Terminal 1: API on http://localhost:8000
cd backend
uv sync
uv run uvicorn app.main:app --reload

# Terminal 2: UI on http://localhost:5173
cd frontend
npm install
npm run dev
```

In development, Vite proxies `/api/*` to the API, so there are no CORS headaches. In production, set `VITE_API_URL` at build time and `ALLOWED_ORIGINS` on the API.

## Tests and checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run build   # typechecks, then builds
```

## Adding a detector

1. Create `backend/app/detectors/my_issue.py` with a function `(DataFrame) -> list[Issue]`. Give each issue a `category` (add a new one to `Category` in `models.py` and `CATEGORIES` in `App.tsx` if none fits).
2. If it needs a new kind of fix, add a step model to `models.py`, add it to `FixStep` and `STEP_ORDER`, and handle it in `transform.py`.
3. Register the detector in `detectors/__init__.py`.
4. Add the matching type to `frontend/src/types.ts`.
5. Write tests first. Each detector and fix has its own.

## Roadmap

- [x] Detectors: whitespace and casing, mixed types (numbers), outliers
- [x] Fuzzy category matching (typos, punctuation) with user-reviewed merges
- [ ] Detectors: constant columns, mixed date formats
- [ ] Before/after preview of affected rows
- [ ] Excel and JSON input
- [ ] Deploy (API + static frontend)
- [ ] AI layer: describe the cleanup in plain English and get suggested fixes

## Privacy rules for contributors

- Never write file contents to disk.
- Never log cell values, or raw pandas exception text (it can echo data). Log metadata only.
- Validation errors must not echo submitted input (`include_input=False`).
