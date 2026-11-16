# Data Cleaner

A web app for analysts. Upload a messy CSV, review the data quality issues it finds, choose how to fix each one, and download a cleaned CSV.

**Privacy by design:** files are processed in memory and never stored. There is no database, no file storage, and no logging of file contents.

## How it works

1. `POST /analyze` receives the CSV and returns a list of issues (missing values, duplicate rows, ...). Each issue has a count, a few sample rows, and a menu of possible fixes.
2. The user picks a fix for each issue in the browser.
3. `POST /transform` receives the same CSV again plus the chosen fixes, applies them, and returns the cleaned CSV.

The server is stateless, so the browser keeps the file between steps and re-sends it. Uploads are capped at 25 MB (set `MAX_UPLOAD_MB` to change it).

**Untouched data stays untouched.** Every cell is read as text and only empty cells count as missing, so leading zeros (`00123`), values like `NA` or `None`, and integer formatting survive. The cleaned file is written with the upload's delimiter, encoding and line endings. Numbers are only parsed where a fix needs them (mean, median). See `backend/app/csv_io.py`.

### Fix steps

Each fix is a small JSON object discriminated by `op`, validated with Pydantic (`backend/app/models.py`) and mirrored in TypeScript (`frontend/src/types.ts`):

```json
{"op": "fill_nulls", "column": "age", "strategy": "median"}
{"op": "drop_null_rows", "column": "name"}
{"op": "drop_duplicates", "keep": "first"}
```

Steps always run in a **fixed order** (fill nulls, then drop rows, then drop duplicates), not the order they were chosen. That makes results predictable, and it means rows that become identical after a fill are caught as duplicates. See `STEP_ORDER` in `models.py`.

## Project layout

```
backend/            FastAPI + pandas
  app/
    main.py         endpoints
    models.py       issue and fix-step schemas
    csv_io.py       encoding/delimiter detection, CSV in and out
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

1. Create `backend/app/detectors/my_issue.py` with a function `(DataFrame) -> list[Issue]`.
2. If it needs a new kind of fix, add a step model to `models.py`, add it to `FixStep` and `STEP_ORDER`, and handle it in `transform.py`.
3. Register the detector in `detectors/__init__.py`.
4. Add the matching type to `frontend/src/types.ts`.
5. Write tests first. Each detector and fix has its own.

## Roadmap

- [ ] Detectors: whitespace and casing, mixed types, constant columns
- [ ] Detectors: inconsistent categories (fuzzy matching), mixed date formats, outliers
- [ ] Before/after preview of affected rows
- [ ] Excel and JSON input
- [ ] Deploy (API + static frontend)
- [ ] AI layer: describe the cleanup in plain English and get suggested fixes

## Privacy rules for contributors

- Never write file contents to disk.
- Never log cell values, or raw pandas exception text (it can echo data). Log metadata only.
- Validation errors must not echo submitted input (`include_input=False`).
