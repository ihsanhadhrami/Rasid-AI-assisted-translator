"""Gradio review UI. UI code only: all logic lives in pipeline.py and below.

Usage: uv run python -m rasid.app   (then open http://127.0.0.1:7860)
"""

import time
from datetime import date

import gradio as gr
import pandas as pd

from rasid import pipeline, storage
from rasid.checks import format_checks
from rasid.config import get_settings
from rasid.languages import NAMES, Direction, DirectionError, resolve_direction
from rasid.llm import LLMError
from rasid.schemas import CheckResult, PipelineOutput

FROM_CHOICES = [("Auto", "auto"), ("Malay", "ms"), ("English", "en"), ("Arabic", "ar")]
TO_CHOICES = {
    "auto": [("Default", "auto"), ("Arabic", "ar"), ("Malay", "ms"), ("English", "en")],
    "ms": [("Arabic", "ar")],
    "en": [("Arabic", "ar")],
    "ar": [("Malay", "ms"), ("English", "en")],
}
FACT_COLS = ["kind", "source", "target"]
ISSUE_COLS = ["severity", "category", "source", "target", "explanation", "suggestion"]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def on_from_change(source_lang: str):
    choices = TO_CHOICES[source_lang]
    return gr.update(choices=choices, value=choices[0][1]), gr.update(
        rtl=source_lang == "ar"
    )


def checks_md(checks: list[CheckResult]) -> str:
    return format_checks(checks).replace("\n", "\n\n")


def flags_md(out: PipelineOutput) -> str:
    if not out.draft.flags:
        return "_No flags._"
    lines = []
    for f in out.draft.flags:
        kind = "honorific (confirm the title)" if f.kind == "honorific" else f.kind
        lines.append(f"- **{kind}** · `{f.source_span}`: {f.note}")
    return "\n".join(lines)


def header_md(out: PipelineOutput) -> str:
    u = out.usage
    return (
        f"### {out.draft.title}\n\n"
        f"{out.draft.summary}\n\n"
        f"<small>{NAMES[out.source_lang]} → {NAMES[out.target_lang]} · "
        f"{out.draft.source_type} · model {u[0].model} · "
        f"{sum(x.input_tokens for x in u)} in / {sum(x.output_tokens for x in u)} out tokens · "
        f"AI {out.ai_seconds:.0f}s · run {out.run_id[:8]}</small>"
    )


def on_draft(article: str, source_name: str, article_date: str, src: str, tgt: str):
    if not article.strip():
        raise gr.Error("Paste an article first.")
    source_name, article_date = source_name.strip(), article_date.strip()
    try:
        direction = resolve_direction(article, src, None if tgt == "auto" else tgt)
    except DirectionError as e:
        raise gr.Error(str(e)) from e
    try:
        out = pipeline.run(article, source_name, article_date, direction)
    except LLMError as e:
        raise gr.Error(f"Model call failed: {e}") from e
    storage.save_draft(out, article, source_name, article_date)
    return show_run(out, article, "Draft ready. Review time is running.")


def resume_label(r) -> str:
    created = r["created_at"][:16].replace("T", " ")
    title = (r["title"] or "")[:60]
    return f"{created} · {r['source_name'] or '?'} · {r['source_lang']}→{r['target_lang']} · {title}"


def resume_choices():
    choices = [(resume_label(r), r["run_id"]) for r in storage.list_unapproved()]
    return gr.update(choices=choices, value=None)


def on_resume(run_id: str | None):
    if not run_id:
        raise gr.Error("Pick a draft to resume.")
    out, row = storage.load_run(run_id)
    shown = show_run(
        out,
        row["source_text"],
        "Draft resumed (no API call). Review time restarted from now.",
    )
    return (
        row["source_text"],
        row["source_name"] or "",
        row["article_date"] or "",
        gr.update(value=out.source_lang),
        gr.update(choices=TO_CHOICES[out.source_lang], value=out.target_lang),
        *shown,
    )


def show_run(out: PipelineOutput, article: str, status: str):
    target = NAMES[out.target_lang]
    to_ar = out.target_lang == "ar"
    facts = pd.DataFrame(
        [[f.kind, f.source, f.target] for f in out.draft.facts], columns=FACT_COLS
    )
    issues = sorted(out.review.issues, key=lambda i: SEVERITY_ORDER[i.severity])
    issues_df = pd.DataFrame(
        [
            [
                i.severity,
                i.category,
                i.source_span,
                i.target_span,
                i.explanation,
                i.suggestion,
            ]
            for i in issues
        ],
        columns=ISSUE_COLS,
    )
    state = {"out": out, "article": article, "shown_at": time.time()}
    return (
        state,
        header_md(out),
        gr.update(rtl=out.source_lang == "ar"),
        gr.update(
            value=out.draft.translation, rtl=to_ar, label=f"{target} draft (editable)"
        ),
        checks_md(out.checks),
        facts,
        issues_df,
        flags_md(out),
        gr.update(
            value=out.draft.significance_draft,
            rtl=to_ar,
            label=f"Significance: AI DRAFT in {target}, rewrite before approving",
        ),
        gr.update(value="", rtl=to_ar),
        status,
    )


def on_recheck(state: dict | None, translation: str):
    if not state:
        raise gr.Error("Draft an article first.")
    out: PipelineOutput = state["out"]
    direction = Direction(out.source_lang, out.target_lang)
    return checks_md(
        pipeline.check_pass(state["article"], out.draft, direction, translation)
    )


def on_approve(
    state: dict | None,
    translation: str,
    significance: str,
    assessment: str,
    baseline: float | None,
):
    if not state:
        raise gr.Error("Draft an article first.")
    out: PipelineOutput = state["out"]
    review_seconds = time.time() - state["shown_at"]
    try:
        path = pipeline.approve(
            out.run_id,
            translation,
            significance,
            assessment,
            review_seconds,
            baseline or None,  # an empty gr.Number arrives as 0, not None
        )
    except pipeline.ApprovalError as e:
        raise gr.Error(str(e)) from e
    rate = storage.edit_rate(out.draft.translation, translation)
    return (
        f"✅ Approved and saved (run {out.run_id[:8]}). "
        f"Review time {review_seconds / 60:.1f} min · edit rate {rate:.1%} · "
        f"exported to `{path}`"
    )


def build() -> gr.Blocks:
    with gr.Blocks(title="Rāṣid") as demo:
        gr.Markdown("## Rāṣid (راصد): the AI drafts and checks, you decide")
        state = gr.State(None)
        with gr.Row():
            resume_dd = gr.Dropdown(
                [], label="Resume a saved draft (not yet approved)", scale=4
            )
            resume_btn = gr.Button("Load draft", scale=1)
            refresh_btn = gr.Button("Refresh list", scale=1)
        with gr.Row():
            source_name = gr.Textbox(label="Source name", placeholder="Bernama")
            article_date = gr.Textbox(label="Date", value=date.today().isoformat())
            src = gr.Dropdown(FROM_CHOICES, value="auto", label="From")
            tgt = gr.Dropdown(TO_CHOICES["auto"], value="auto", label="To")
            baseline = gr.Number(
                label="Manual baseline, minutes (optional)", value=None, minimum=0
            )
        with gr.Row():
            article = gr.Textbox(label="Source article", lines=18, max_lines=40)
            translation = gr.Textbox(
                label="Translation draft (editable)", lines=18, max_lines=40
            )
        with gr.Row():
            draft_btn = gr.Button("Draft", variant="primary")
            recheck_btn = gr.Button("Re-run checks on my edits")
        header = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("**Checks**")
                checks = gr.Markdown()
            with gr.Column(scale=2):
                facts = gr.Dataframe(
                    headers=FACT_COLS, label="Fact table", interactive=False, wrap=True
                )
        issues = gr.Dataframe(
            headers=ISSUE_COLS, label="Reviewer issues", interactive=False, wrap=True
        )
        gr.Markdown("**Flags**")
        flags = gr.Markdown()
        with gr.Row():
            significance = gr.Textbox(label="Significance: AI DRAFT", lines=4)
            assessment = gr.Textbox(
                label="Source assessment (you write this; required to approve)",
                lines=4,
            )
        approve_btn = gr.Button("Approve & save", variant="primary")
        status = gr.Markdown()

        run_outputs = [
            state,
            header,
            article,
            translation,
            checks,
            facts,
            issues,
            flags,
            significance,
            assessment,
            status,
        ]
        # .input, not .change: fires only on user clicks, so resuming a draft
        # (which sets From and To itself) doesn't reset the To choice.
        src.input(on_from_change, src, [tgt, article])
        draft_btn.click(
            on_draft, [article, source_name, article_date, src, tgt], run_outputs
        ).then(resume_choices, None, resume_dd)
        resume_btn.click(
            on_resume,
            resume_dd,
            [article, source_name, article_date, src, tgt, *run_outputs],
        )
        refresh_btn.click(resume_choices, None, resume_dd)
        recheck_btn.click(on_recheck, [state, translation], checks)
        approve_btn.click(
            on_approve, [state, translation, significance, assessment, baseline], status
        ).then(resume_choices, None, resume_dd)
        demo.load(resume_choices, None, resume_dd)
    return demo


def main() -> None:
    secret = get_settings().rasid_password
    password = secret.get_secret_value() if secret else ""
    if not password:
        raise SystemExit("Set RASID_PASSWORD in .env before launching the UI.")
    build().queue().launch(
        server_name="127.0.0.1",
        share=False,
        auth=("ihsan", password),
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
