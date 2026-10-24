"""SQLite run log: one row per drafted brief, completed when the human approves it."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from rasid.config import RUNS_DIR
from rasid.schemas import (
    CheckResult,
    DraftResult,
    PipelineOutput,
    ReviewResult,
    Usage,
)

DB_PATH = RUNS_DIR / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  source_name TEXT, article_date TEXT,
  source_lang TEXT NOT NULL,          -- ms | en | ar (resolved, not "auto")
  target_lang TEXT NOT NULL,          -- ar | ms | en
  source_text TEXT NOT NULL,
  ai_draft_json TEXT NOT NULL,        -- full DraftResult
  checks_json TEXT NOT NULL,
  review_json TEXT NOT NULL,
  final_translation TEXT,             -- NULL until approved
  final_significance TEXT,
  source_assessment TEXT,             -- written by the human only
  edit_rate REAL,                     -- 1 - rapidfuzz normalized similarity
  ai_seconds REAL,
  review_seconds REAL,                -- draft shown -> approve clicked
  manual_baseline_minutes REAL,       -- optional: entered when you time a manual brief
  model TEXT,                         -- the model that actually served the draft
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
  approved INTEGER DEFAULT 0
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def edit_rate(ai_text: str, final_text: str) -> float:
    """0 = unchanged, near 1 = rewritten."""
    return round(1 - Levenshtein.normalized_similarity(ai_text, final_text), 4)


def save_draft(
    out: PipelineOutput,
    source_text: str,
    source_name: str,
    article_date: str,
    path: Path = DB_PATH,
) -> None:
    """Log the AI output as soon as it exists, so unapproved drafts are kept too."""
    row = {
        "run_id": out.run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_name": source_name,
        "article_date": article_date,
        "source_lang": out.source_lang,
        "target_lang": out.target_lang,
        "source_text": source_text,
        "ai_draft_json": out.draft.model_dump_json(),
        "checks_json": json.dumps(
            [c.model_dump() for c in out.checks], ensure_ascii=False
        ),
        "review_json": out.review.model_dump_json(),
        "ai_seconds": out.ai_seconds,
        "model": out.usage[0].model,
        "input_tokens": sum(u.input_tokens for u in out.usage),
        "output_tokens": sum(u.output_tokens for u in out.usage),
        "cache_read_tokens": sum(u.cache_read_tokens for u in out.usage),
    }
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    with closing(connect(path)) as conn, conn:
        conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", row)


def approve(
    run_id: str,
    final_translation: str,
    final_significance: str,
    source_assessment: str,
    review_seconds: float,
    manual_baseline_minutes: float | None = None,
    path: Path = DB_PATH,
) -> sqlite3.Row:
    """Record the human's final text. Approving again overwrites the earlier approval."""
    with closing(connect(path)) as conn, conn:
        row = get_run(run_id, conn)
        ai_translation = json.loads(row["ai_draft_json"])["translation"]
        conn.execute(
            """UPDATE runs SET final_translation = ?, final_significance = ?,
                 source_assessment = ?, edit_rate = ?, review_seconds = ?,
                 manual_baseline_minutes = ?, approved = 1
               WHERE run_id = ?""",
            (
                final_translation,
                final_significance,
                source_assessment,
                edit_rate(ai_translation, final_translation),
                round(review_seconds, 1),
                manual_baseline_minutes,
                run_id,
            ),
        )
        return get_run(run_id, conn)


def get_run(run_id: str, conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"No run {run_id!r} in the database")
    return row


def list_unapproved(path: Path = DB_PATH, limit: int = 50) -> list[sqlite3.Row]:
    """Drafts not yet approved, newest first."""
    with closing(connect(path)) as conn:
        return conn.execute(
            """SELECT run_id, created_at, source_name, article_date, source_lang,
                      target_lang, json_extract(ai_draft_json, '$.title') AS title
               FROM runs WHERE approved = 0 ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def load_run(run_id: str, path: Path = DB_PATH) -> tuple[PipelineOutput, sqlite3.Row]:
    """Rebuild a saved run without calling the API. Usage comes back as one summed entry."""
    with closing(connect(path)) as conn:
        row = get_run(run_id, conn)
    out = PipelineOutput(
        run_id=row["run_id"],
        source_lang=row["source_lang"],
        target_lang=row["target_lang"],
        draft=DraftResult.model_validate_json(row["ai_draft_json"]),
        checks=[CheckResult.model_validate(c) for c in json.loads(row["checks_json"])],
        review=ReviewResult.model_validate_json(row["review_json"]),
        usage=[
            Usage(
                model=row["model"] or "",
                input_tokens=row["input_tokens"] or 0,
                output_tokens=row["output_tokens"] or 0,
                cache_read_tokens=row["cache_read_tokens"] or 0,
            )
        ],
        ai_seconds=row["ai_seconds"] or 0.0,
    )
    return out, row
