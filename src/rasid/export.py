"""Brief export. v1: Markdown in the target language's template. DOCX comes in Phase 6."""

import json
import re
import sqlite3
from pathlib import Path

from rasid.config import DATA_DIR, RUNS_DIR

EXPORT_DIR = RUNS_DIR / "exports"


def render_markdown(row: sqlite3.Row | dict) -> str:
    """Fill `data/brief_template_{target}.md` from an approved run."""
    draft = json.loads(row["ai_draft_json"])
    template = (DATA_DIR / f"brief_template_{row['target_lang']}.md").read_text(
        encoding="utf-8"
    )
    values = {
        "title": draft["title"],
        "source_name": row["source_name"] or "",
        "date": row["article_date"] or "",
        "summary": draft["summary"],
        "translation": row["final_translation"].strip(),
        "significance": row["final_significance"].strip(),
        "source_assessment": row["source_assessment"].strip(),
    }
    # str.replace, not str.format: article text may contain braces.
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def write_markdown(row: sqlite3.Row | dict, out_dir: Path = EXPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    date = re.sub(r"[^\w-]", "", row["article_date"] or "") or "undated"
    path = out_dir / f"{date}_{row['run_id'][:8]}_{row['target_lang']}.md"
    path.write_text(render_markdown(row), encoding="utf-8")
    return path
