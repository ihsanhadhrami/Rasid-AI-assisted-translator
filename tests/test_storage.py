"""SQLite logging, approval and Markdown export (no API calls)."""

from contextlib import closing

import pytest

from rasid import pipeline, storage
from rasid.export import render_markdown
from rasid.schemas import DraftResult, PipelineOutput, ReviewResult, Usage


def make_output(
    target_lang: str = "ar", translation: str = "نص الترجمة"
) -> PipelineOutput:
    draft = DraftResult(
        detected_source_lang="ar" if target_lang != "ar" else "ms",
        title="Tajuk {ujian}",
        summary="Ringkasan.",
        translation=translation,
        facts=[],
        flags=[],
        significance_draft="Draf kepentingan.",
        source_type="news_report",
    )
    usage = [
        Usage(
            model="m-draft", input_tokens=100, output_tokens=50, cache_read_tokens=10
        ),
        Usage(model="m-review", input_tokens=40, output_tokens=5),
    ]
    return PipelineOutput(
        run_id="12345678-aaaa-bbbb-cccc-000000000000",
        source_lang=draft.detected_source_lang,
        target_lang=target_lang,
        draft=draft,
        checks=[],
        review=ReviewResult(issues=[]),
        usage=usage,
        ai_seconds=12.5,
    )


@pytest.fixture
def db(tmp_path):
    return tmp_path / "runs.db"


def fetch(db, run_id):
    with closing(storage.connect(db)) as conn:
        return storage.get_run(run_id, conn)


def test_edit_rate_bounds():
    assert storage.edit_rate("abc", "abc") == 0
    assert storage.edit_rate("abc", "xyz") == 1
    assert 0 < storage.edit_rate("abcd", "abcx") < 1


def test_save_draft_logs_unapproved_row_with_summed_usage(db):
    out = make_output()
    storage.save_draft(out, "Teks sumber", "Bernama", "2026-10-19", db)
    row = fetch(db, out.run_id)
    assert row["approved"] == 0
    assert row["final_translation"] is None
    assert row["model"] == "m-draft"
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (
        140,
        55,
        10,
    )
    assert DraftResult.model_validate_json(row["ai_draft_json"]) == out.draft


def test_approve_requires_source_assessment(db, tmp_path):
    out = make_output()
    storage.save_draft(out, "src", "Bernama", "2026-10-19", db)
    with pytest.raises(pipeline.ApprovalError):
        pipeline.approve(
            out.run_id, "نص", "sig", "   ", 30, db_path=db, export_dir=tmp_path
        )
    assert fetch(db, out.run_id)["approved"] == 0


def test_approve_saves_and_exports(db, tmp_path):
    out = make_output(translation="نص الترجمة الأول")
    storage.save_draft(out, "src", "Bernama", "2026-10-19", db)
    path = pipeline.approve(
        out.run_id,
        "نص الترجمة المعدل",
        "أهمية",
        "مصدر رسمي موثوق",
        95.04,
        20,
        db_path=db,
        export_dir=tmp_path,
    )
    row = fetch(db, out.run_id)
    assert row["approved"] == 1
    assert row["review_seconds"] == 95.0
    assert row["manual_baseline_minutes"] == 20
    assert 0 < row["edit_rate"] < 1
    assert path.name == "2026-10-19_12345678_ar.md"
    text = path.read_text(encoding="utf-8")
    assert "**تقييم المصدر:** مصدر رسمي موثوق" in text
    assert "نص الترجمة المعدل" in text and "الأول" not in text


def test_approve_unknown_run_raises(db, tmp_path):
    storage.connect(db).close()
    with pytest.raises(KeyError):
        pipeline.approve("nope", "t", "s", "a", 1, db_path=db, export_dir=tmp_path)


@pytest.mark.parametrize(
    ("target", "label"),
    [("ar", "**الترجمة:**"), ("ms", "**Terjemahan:**"), ("en", "**Translation:**")],
)
def test_render_uses_target_template_and_leaves_no_placeholders(target, label):
    out = make_output(target)
    row = {
        "run_id": out.run_id,
        "target_lang": target,
        "source_name": "Al Jazeera Net",
        "article_date": "2026-04-21",
        "ai_draft_json": out.draft.model_dump_json(),
        "final_translation": "Final {text}",
        "final_significance": "Sig",
        "source_assessment": "Assessed",
    }
    md = render_markdown(row)
    assert label in md
    assert "Tajuk {ujian}" in md  # braces in content survive
    assert "{source_assessment}" not in md and "{translation}" not in md


def test_schema_matches_spec_columns(db):
    with closing(storage.connect(db)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    assert {
        "edit_rate",
        "review_seconds",
        "source_assessment",
        "model",
        "approved",
    } <= cols


def test_resume_lists_unapproved_and_rebuilds_the_run(db, tmp_path):
    out = make_output("en", translation="English text")
    storage.save_draft(out, "نص المصدر", "Al Jazeera Net", "2026-04-21", db)
    rows = storage.list_unapproved(db)
    assert [r["run_id"] for r in rows] == [out.run_id]
    assert rows[0]["title"] == out.draft.title

    loaded, row = storage.load_run(out.run_id, db)
    assert loaded.draft == out.draft and loaded.review == out.review
    assert loaded.usage[0].input_tokens == 140
    assert row["source_text"] == "نص المصدر"

    pipeline.approve(out.run_id, "t", "s", "a", 1, db_path=db, export_dir=tmp_path)
    assert storage.list_unapproved(db) == []
