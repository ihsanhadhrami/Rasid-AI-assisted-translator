"""Usage:
uv run python -m rasid.cli evals/articles/001.txt --source "Defence Security Asia" --date 2026-10-13
uv run python -m rasid.cli evals/articles/003.txt --source "Al Jazeera Net" --date 2026-04-21 --to en
uv run python -m rasid.cli evals/articles/003.txt --to en --check runs/003_en.json    # checks only, no API call
uv run python -m rasid.cli evals/articles/003.txt --to en --review runs/003_en.json   # checks + reviewer, no redraft
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from rasid import pipeline
from rasid.checks import format_checks
from rasid.languages import DirectionError, resolve_direction
from rasid.llm import LLMError
from rasid.schemas import DraftResult, ReviewResult, Usage

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def load_draft(path: Path) -> DraftResult:
    """Accept either a saved DraftResult or a full pipeline run (which nests it under "draft")."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return DraftResult.model_validate(data.get("draft", data))


def format_review(review: ReviewResult) -> str:
    if not review.issues:
        return "no issues reported"
    issues = sorted(review.issues, key=lambda i: SEVERITY_ORDER[i.severity])
    return "\n".join(
        f"- [{i.severity}/{i.category}] {i.explanation}\n"
        f"    source: {i.source_span or '-'}\n"
        f"    target: {i.target_span or '-'}\n"
        f"    suggest: {i.suggestion}"
        for i in issues
    )


def format_usage(label: str, u: Usage) -> str:
    return (
        f"[usage:{label}] model={u.model} input={u.input_tokens} output={u.output_tokens} "
        f"cache_read={u.cache_read_tokens} cache_write={u.cache_creation_tokens} seconds={u.seconds}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draft, check and review a translated brief."
    )
    parser.add_argument(
        "article", type=Path, help="UTF-8 text file with the article body"
    )
    parser.add_argument("--source", default="", help="Outlet name, e.g. Bernama")
    parser.add_argument("--date", default="", help="Article date, e.g. 2026-10-16")
    parser.add_argument(
        "--from", dest="source_lang", choices=["auto", "ms", "en", "ar"], default="auto"
    )
    parser.add_argument(
        "--to",
        dest="target_lang",
        choices=["ar", "ms", "en"],
        help="Default: ar for Malay/English sources, ms for Arabic sources",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Also write the full run (draft, checks, review, usage) as JSON",
    )
    saved = parser.add_mutually_exclusive_group()
    saved.add_argument(
        "--check",
        type=Path,
        metavar="DRAFT_JSON",
        help="Skip drafting: run the checks on a saved draft",
    )
    saved.add_argument(
        "--review",
        type=Path,
        metavar="DRAFT_JSON",
        help="Skip drafting: run the checks and the reviewer on a saved draft",
    )
    args = parser.parse_args()

    # Windows consoles default to a legacy code page that can't print Arabic.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    article = args.article.read_text(encoding="utf-8")
    try:
        direction = resolve_direction(article, args.source_lang, args.target_lang)
    except DirectionError as e:
        parser.error(str(e))
    print(
        f"[direction] {direction.source_name} -> {direction.target_name}",
        file=sys.stderr,
    )

    if args.check:
        print(
            format_checks(
                pipeline.check_pass(article, load_draft(args.check), direction)
            )
        )
        return

    try:
        if args.review:
            draft = load_draft(args.review)
            checks = pipeline.check_pass(article, draft, direction)
            review, usage = pipeline.review_pass(
                article, draft.translation, direction, draft.detected_source_lang
            )
            print("[checks]\n" + format_checks(checks))
            print("\n[review]\n" + format_review(review))
            print("\n" + format_usage("review", usage), file=sys.stderr)
            return
        out = pipeline.run(article, args.source, args.date, direction)
    except LLMError as e:
        parser.exit(1, f"error: {e}\n")

    print(json.dumps(out.draft.model_dump(), ensure_ascii=False, indent=2))
    print("\n[checks]\n" + format_checks(out.checks))
    print("\n[review]\n" + format_review(out.review))
    for label, u in zip(("draft", "review"), out.usage, strict=True):
        print(format_usage(label, u), file=sys.stderr)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(out.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
