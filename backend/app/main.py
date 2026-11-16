"""FastAPI app. Stateless by design: uploads are processed in memory and never stored.

Privacy rules for anyone editing this file:
  * Never write file contents to disk.
  * Never log file contents, cell values, or raw exception text from pandas.
  * Log metadata only (row counts, timings).
"""

import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError

from app.config import ALLOWED_ORIGINS, MAX_UPLOAD_BYTES
from app.csv_io import CsvReadError, read_csv, write_csv
from app.detectors import run_detectors
from app.models import AnalyzeResponse, FixStep
from app.transform import TransformError, apply_steps

logger = logging.getLogger("data_cleaner")

app = FastAPI(title="Data Cleaner", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

_steps_adapter = TypeAdapter(list[FixStep])


async def _read_upload(file: UploadFile) -> bytes:
    # Read one byte past the limit so we can tell "exactly at the cap" from "over it".
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    return raw


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)) -> AnalyzeResponse:
    raw = await _read_upload(file)
    try:
        df = read_csv(raw)
    except CsvReadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    issues = run_detectors(df)
    logger.info("analyzed rows=%d cols=%d issues=%d", len(df), len(df.columns), len(issues))
    return AnalyzeResponse(rows=len(df), columns=[str(c) for c in df.columns], issues=issues)


@app.post("/transform")
async def transform(
    file: UploadFile = File(...),
    steps: str = Form("[]", description="JSON array of fix steps"),
) -> Response:
    try:
        parsed = _steps_adapter.validate_json(steps)
    except ValidationError as e:
        # include_input=False keeps submitted values out of the error payload.
        raise HTTPException(
            status_code=422, detail=e.errors(include_input=False, include_url=False)
        ) from None

    raw = await _read_upload(file)
    try:
        df = read_csv(raw)
        cleaned = apply_steps(df, parsed)
    except CsvReadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except TransformError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    logger.info("transformed rows_in=%d rows_out=%d steps=%d", len(df), len(cleaned), len(parsed))
    return Response(
        content=write_csv(cleaned),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="cleaned.csv"',
            "Cache-Control": "no-store",
        },
    )
