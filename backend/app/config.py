"""Runtime settings. Everything is overridable with environment variables."""

import os

# Hard cap on upload size. The server is stateless, so every request re-sends the file;
# a cap keeps requests fast and memory use predictable.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024

# Comma-separated list of origins allowed to call the API from a browser.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# How many example rows to show per issue. Display only, never persisted.
SAMPLE_ROWS = 3

# Columns with at least this share of empty cells (placeholders like "N/A" included) are
# removed by default. The UI lists them, and the user can keep any of them.
DROP_COLUMN_MISSING_SHARE = float(os.getenv("DROP_COLUMN_MISSING_SHARE", "0.5"))
