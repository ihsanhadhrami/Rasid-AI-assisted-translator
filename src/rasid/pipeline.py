import time
import uuid
from functools import lru_cache
from pathlib import Path

from rasid import llm, storage
from rasid.checks import run_checks
from rasid.config import DATA_DIR, PROMPTS_DIR
from rasid.export import EXPORT_DIR, write_markdown
from rasid.glossary import GlossaryEntry, format_for_prompt, load_glossary
from rasid.languages import NAMES, Direction
from rasid.schemas import (
    CheckResult,
    DraftResult,
    PipelineOutput,
    ReviewResult,
    Usage,
)

# House style for Malay/English output (Arabic output style lives in drafter_to_arabic.md).
TARGET_PROFILES = {
    "ms": {
        "target_style": "standard Malay, Bahasa Melayu baku, Dewan Bahasa dan Pustaka spelling",
        "attribution": "menurut / dipetik sebagai berkata / dilaporkan",
        "date_rule": "write as '21 April 2026' with Malay month names "
        "(Januari, Februari, Mac, April, Mei, Jun, Julai, Ogos, September, Oktober, November, Disember).",
    },
    "en": {
        "target_style": "Bernama English, British spelling",
        "attribution": "according to / said / reportedly",
        "date_rule": "write as '21 April 2026'.",
    },
}


@lru_cache
def glossary() -> list[GlossaryEntry]:
    return load_glossary(DATA_DIR / "glossary.csv")


def _style_notes(target_lang: str) -> str:
    path = DATA_DIR / f"style_notes_{target_lang}.md"
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return text or "(none)"


@lru_cache
def drafter_system_prompt(target_lang: str) -> str:
    """One prompt per target language, built once and kept byte-identical so prompt caching can hit."""
    to_arabic = target_lang == "ar"
    template = (
        PROMPTS_DIR
        / ("drafter_to_arabic.md" if to_arabic else "drafter_from_arabic.md")
    ).read_text(encoding="utf-8")
    source_lang = "ms/en" if to_arabic else "ar"
    values = {
        "glossary_table": format_for_prompt(glossary(), source_lang, target_lang),
        "style_notes": _style_notes(target_lang),
        "target_language": NAMES[target_lang],
        **TARGET_PROFILES.get(target_lang, {}),
    }
    # str.replace, not str.format: the notes may contain braces.
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


# Grammar points the reviewer should watch in each target language.
GRAMMAR_FOCUS = {
    "ar": "especially gender and number agreement between verb, subject and adjective",
    "ms": "especially affixes (imbuhan), word order and the choice of attribution verb",
    "en": "especially tense consistency, articles and the choice of attribution verb",
}


# Deliberate departures from the source that the reviewer should not report.
_HONORIFICS = (
    "Malaysian honorifics (Datuk Seri, Tan Sri, Tun, royal styles) are added per Bernama "
    "style even when the source omits them. Do not report them as additions; report one "
    "only if it is wrong for that person."
)
HOUSE_RULES = {"ar": "(none)", "ms": _HONORIFICS, "en": _HONORIFICS}


@lru_cache
def reviewer_system_prompt(source_lang: str, target_lang: str) -> str:
    """One prompt per direction, kept byte-identical so prompt caching can hit."""
    template = (PROMPTS_DIR / "reviewer_system.md").read_text(encoding="utf-8")
    glossary_source = "ar" if source_lang == "ar" else "ms/en"
    values = {
        "source_language": NAMES.get(source_lang, "Malay/English"),
        "target_language": NAMES[target_lang],
        "grammar_focus": GRAMMAR_FOCUS[target_lang],
        "house_rules": HOUSE_RULES[target_lang],
        "glossary_table": format_for_prompt(glossary(), glossary_source, target_lang),
    }
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def _escape(text: str, tag: str = "article") -> str:
    """Stop data text from closing its own tag."""
    return text.replace(f"</{tag}>", f"&lt;/{tag}&gt;")


def draft_user_message(
    article: str, source_name: str, date: str, direction: Direction
) -> str:
    source = (
        "auto (detect: ms or en)" if direction.source == "auto" else direction.source
    )
    return (
        "<metadata>\n"
        f"source: {source_name}\n"
        f"date: {date}\n"
        f"source_language: {source}\n"
        f"target_language: {direction.target}\n"
        "</metadata>\n"
        "<article>\n"
        f"{_escape(article.strip())}\n"
        "</article>"
    )


def draft_pass(
    article: str, source_name: str, date: str, direction: Direction
) -> tuple[DraftResult, Usage]:
    """Pass 1: translation, fact table, flags and draft significance."""
    return llm.call_structured(
        drafter_system_prompt(direction.target),
        draft_user_message(article, source_name, date, direction),
        DraftResult,
    )


def check_pass(
    article: str,
    draft: DraftResult,
    direction: Direction,
    translation: str | None = None,
) -> list[CheckResult]:
    """Deterministic checks on the draft, or on the human's edited `translation`."""
    return run_checks(article, draft, direction, glossary(), translation)


def review_user_message(article: str, translation: str) -> str:
    return (
        "<source>\n"
        f"{_escape(article.strip(), 'source')}\n"
        "</source>\n"
        "<translation>\n"
        f"{_escape(translation.strip(), 'translation')}\n"
        "</translation>"
    )


def review_pass(
    article: str, translation: str, direction: Direction, source_lang: str | None = None
) -> tuple[ReviewResult, Usage]:
    """Pass 2: an independent reviewer compares source and translation.

    `source_lang` overrides an "auto" direction once the drafter has detected ms or en.
    """
    source = source_lang or direction.source
    return llm.call_structured(
        reviewer_system_prompt(source, direction.target),
        review_user_message(article, translation),
        ReviewResult,
    )


def run(
    article: str, source_name: str, date: str, direction: Direction
) -> PipelineOutput:
    """Draft -> deterministic checks -> independent review."""
    t0 = time.perf_counter()
    draft, u1 = draft_pass(article, source_name, date, direction)
    checks = check_pass(article, draft, direction)
    review, u2 = review_pass(
        article, draft.translation, direction, draft.detected_source_lang
    )
    return PipelineOutput(
        run_id=str(uuid.uuid4()),
        source_lang=draft.detected_source_lang,
        target_lang=direction.target,
        draft=draft,
        checks=checks,
        review=review,
        usage=[u1, u2],
        ai_seconds=round(time.perf_counter() - t0, 2),
    )


class ApprovalError(ValueError):
    pass


def approve(
    run_id: str,
    final_translation: str,
    final_significance: str,
    source_assessment: str,
    review_seconds: float,
    manual_baseline_minutes: float | None = None,
    db_path: Path = storage.DB_PATH,
    export_dir: Path = EXPORT_DIR,
) -> Path:
    """Save the human-approved brief and export it. The source assessment is the human's step."""
    if not source_assessment.strip():
        raise ApprovalError("Write the source assessment before approving.")
    if not final_translation.strip():
        raise ApprovalError("The translation is empty.")
    row = storage.approve(
        run_id,
        final_translation,
        final_significance,
        source_assessment,
        review_seconds,
        manual_baseline_minutes,
        db_path,
    )
    return write_markdown(row, export_dir)
