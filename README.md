# Data Cleaner

A web app for analysts. Upload a messy CSV, review the data quality issues it finds, choose how to fix each one, and download a cleaned CSV.

**Privacy by design:** files are processed in memory and never stored. There is no database, no file storage, and no logging of file contents.

## How it works

1. `POST /analyze` receives the CSV and returns a list of issues. Each issue belongs to a category (missingness, inconsistent data, outliers, data type mismatch, duplicate rows) and has a count, a one-line detail, a few sample rows, and a menu of possible fixes. The UI shows a summary per category rather than a preview per column.
2. The user picks a fix for each issue in the browser.
3. `POST /transform` receives the same CSV again plus the chosen fixes, applies them, and returns the cleaned CSV.

The server is stateless, so the browser keeps the file between steps and re-sends it. Uploads are capped at 25 MB (set `MAX_UPLOAD_MB` to change it).

**Untouched data stays untouched.** Every cell is read as text, so leading zeros (`00123`) and integer formatting survive. Placeholders like `N/A` or `NULL` count as missing values (see below) but are written back exactly as uploaded unless the user picks a fix for them. Blank and repeated headers, which pandas renames (`Unnamed: 12`, `a.1`), are written back as they were. The cleaned file is written with the upload's delimiter, encoding and line endings. Numbers are only parsed where a check or fix needs them (mean, median, outliers, type mismatch). See `backend/app/csv_io.py`.

### Fix steps

Each fix is a small JSON object discriminated by `op`, validated with Pydantic (`backend/app/models.py`) and mirrored in TypeScript (`frontend/src/types.ts`):

```json
{"op": "drop_columns", "columns": ["Unnamed: 12", "fax"]}
{"op": "standardize_values", "column": "city", "case": "title", "merge": {"new yrok": "new york"}, "rename": {"nyc": "New York City"}}
{"op": "fix_type_mismatch", "column": "age", "action": "clear"}
{"op": "fix_invalid", "column": "age", "min": 0, "max": 120, "action": "clear"}
{"op": "fix_outliers", "column": "age", "lower": 18, "upper": 90, "action": "cap"}
{"op": "fix_outliers", "column": "income", "upper_pct": 99, "action": "cap"}
{"op": "fill_nulls", "column": "age", "strategy": "median"}
{"op": "clear_placeholders", "column": "age"}
{"op": "drop_null_rows", "column": "name"}
{"op": "drop_duplicates", "keep": "first"}
```

Steps always run in a **fixed order** (the order above), not the order they were chosen. Values are fixed first (spellings, stray text, then outliers, so a mean fill isn't skewed by them), then gaps are filled or dropped, and duplicates are checked last so rows that become identical after earlier fixes are caught. See `STEP_ORDER` in `models.py`.

### Detectors

| Category | What counts | Rule |
|---|---|---|
| Missingness | Empty cells and placeholders | Empty or space-only cells, and placeholder text (see below) |
| Inconsistent data | Same value written differently | Case and spacing variants are grouped; in categories, the column's usual case style is applied and near-duplicates (typos, punctuation) are suggested as merges |
| Invalid values | Numbers that break a rule | Rules suggested from the column name (age 0–120, month 1–12, percent 0–100 or 0–1, latitude/longitude, year, non-negative quantities like price or weight) or from the data (≤ 1% negative among 20+ values looks like sign errors); users can edit them or add their own. Recommended fix: clear the cells |
| Outliers | Numbers far from the usual range | Tukey's fences (1.5 × IQR), needs 8+ numbers. Skips IDs, keys and codes (by name, leading zeros, or unique sequential numbers) and ordinal scales. Cut-offs: the usual range, percentiles (1st/99th suggested, 100+ values) or the user's own values |
| Data type mismatch | Text in a number column | Column is at least 80% numbers; the rest is flagged |
| Duplicate rows | Rows that repeat exactly | Count is the extra copies a fix would remove |

Thresholds live in `backend/app/values.py` and `backend/app/categories.py`.

### Reviewing inconsistent categories

For a text column of repeating categories with at most 100 distinct values, the issue includes a `review`: each value (case and spacing variants already grouped) with its row count, how it looks in each case style, and a suggested merge where one fits. In the UI the user picks the case style and can merge any value into another, or type their own value for it ("My own value…"); nothing is applied until they choose. Other text columns (names, free text, or more than 100 values) are only cleaned of case and spacing variants.

- **Case style:** the column's most common style by cells (Title Case, UPPERCASE or lowercase). Guards keep correct values intact: deliberate mixed case (`eBay`, `McDonald`, `O'Neil`) is never changed; in Title Case, short all-caps values (`USA`, `NASA`) and acronyms inside values (`NYC Office`) are kept, small words stay lowercase (`Bank of America`), and only the first letter of a word is capitalized (`They're`, not `They'Re`).
- **Suggested merges:** same letters with different punctuation (`N.Y.C.` → `NYC`), or typos: one edit in words of 5–8 letters, two from 9, only swapped neighbours at 4 letters, none below. The shorter word sets the allowance, so `Austria` is not a typo of `Australia`; values with different numbers (`Room 101`/`Room 102`) never match. Rare values merge into common ones, never in chains.
- **Merges** are keyed by the value's group key (trimmed, single-spaced, lowercased), so they stay valid whichever case style is chosen.
- **Own values** (`rename`: group key → text) are written exactly as typed, minus spaces at the ends, whatever the case style; values merged into one take its new text too. A value is either merged or given its own text, not both.

### Invalid values vs outliers

An **outlier** is unusual but possible (an income of 2,500,000); an **invalid value** breaks a rule (an age of -4, a month of 13). They're fixed differently: outliers can be capped, but capping -4 to 0 would invent an age, so invalid values are cleared (then filled like any missing value, if the user chooses) or their rows dropped. Invalid values are fixed before outliers and left out of outlier detection, so nothing is reported twice.

Name rules have guards against look-alike names: `age_days` is a duration, `price_change` can be negative, and IDs and codes never get rules. Some rules depend on the use case (an age of 4 is fine in a census, not in a customer list), so every suggested rule is editable, and "Add a rule" sets a range on any number column. `/analyze` returns `numbers` (a quantile grid per number column) so the UI can preview any rule without another request. Rules live in `backend/app/rules.py`.

### Outlier cut-offs

Outliers are *detected* with the usual range (Tukey's fences, snapped to real values). To *fix* them the user picks cut-offs, then caps (winsorizes) or drops rows outside them:

- **Usual range** (default): the detected range.
- **Percentiles**: 1st and 99th suggested; offered from 100 values. The server works them out from the column as uploaded, before any other fix runs, and snaps them to real values so whole numbers stay whole.
- **My own values**: for known valid ranges. Inputs start with the usual range.

An empty box means no limit on that side. The UI previews how many values a choice affects (estimated from `cutoffs.quantiles`, the value at every half percentile) and warns above 10%. Percentile cut-offs always change some values, so they are a fix, never a way of detecting outliers.

### Mostly empty columns

Columns with at least half their cells empty (placeholders included) are removed by default: often they're blank columns from trailing commas, which pandas names `Unnamed: 12`. This is the one fix applied without the user choosing it, so the UI shows a collapsible card above the overview ("Removing 2 mostly empty columns"). Opened, it lists each column with how empty it is and whether its header was blank, and a **Keep** button for each: named columns first, then unnamed ones, each least empty first, so the columns most likely to hold data worth keeping lead the list. Issues in removed columns are hidden until the column is kept. `/analyze` returns them as `sparse_columns`; removing them is a normal `drop_columns` step, so the download matches the list. If every column qualifies, none is listed. Set `DROP_COLUMN_MISSING_SHARE` to change the threshold.

### Placeholders for missing values

Text that stands for a missing value counts as missing (`backend/app/placeholders.py`). Matching ignores case and surrounding spaces.

| Placeholder | Where |
|---|---|
| `NULL`, `(null)`, `<null>`, `N/A`, `#N/A`, `<NA>`, `n.a.`, cells of only spaces | Any column |
| `NA`, `NaN`, `missing`, `unknown`, `?`, `not available`, `not applicable` | Number columns only, since `NA` is Namibia's country code and `Nan` is a name |
| `None`, `nil`, `-` | Never: these often mean zero ("children: none"), so in a number column they're a data type mismatch for the user to decide |

Every detector and fix except the missing-values detector sees placeholders as empty cells, so `N/A` among ages is a missing value rather than a type mismatch, and `n/a` vs `N/A` isn't an inconsistency. Filling or dropping missing values covers placeholders too. Placeholders still missing after the fixes are written back as uploaded, unless the user chose "Make placeholders empty" (`clear_placeholders`). That fix is recommended when no fill value fits, such as IDs or free text.

### Recommended fill for missing values

Each missing-values issue marks one fix as `recommended` and explains why in its `detail` line. The UI tags that option and offers "Use recommended fixes"; nothing is applied until the user chooses. The choice follows the kind of data (`column_kind` in `values.py`):

| Column holds | Example | Recommended |
|---|---|---|
| Roughly normal numbers (\|skewness\| ≤ 0.5 and \|excess kurtosis\| ≤ 1, 20+ values) | heights | Mean |
| Other numbers (skewed, heavy- or light-tailed, or too few to judge) | incomes | Median |
| An ordinal scale: whole numbers spanning ≤ 10 steps that repeat | satisfaction 1–10, Likert 1–5, 0/1 flags | Mode |
| Text categories that repeat (≤ 50% distinct) | city, plan tier | Mode |
| IDs or free text (values rarely repeat) | `customer_id`, notes | Leave as is (or make placeholders empty, if it has any) |

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
    placeholders.py text that stands for a missing value ("N/A", "NULL")
    rules.py        validity rules: from column names, from the data
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
- [x] Invalid values: suggested and user-defined validity rules
- [ ] Detectors: constant columns, mixed date formats
- [ ] Before/after preview of affected rows
- [ ] Excel and JSON input
- [ ] Deploy (API + static frontend)
- [ ] AI layer: describe the cleanup in plain English and get suggested fixes

## Privacy rules for contributors

- Never write file contents to disk.
- Never log cell values, or raw pandas exception text (it can echo data). Log metadata only.
- Validation errors must not echo submitted input (`include_input=False`).
