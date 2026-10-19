"""Phase 3 acceptance test: does the reviewer catch planted errors?

For each direction family, take a real draft, plant one omission and one grammar/attribution
error, and run the reviewer N times. Pass = the omission is reported as critical or major
in at least 4 of 5 attempts.

Usage: uv run python evals/reviewer_plant_test.py [--attempts 5]
Costs one reviewer call per attempt per case.
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from rasid import pipeline
from rasid.checks import format_checks
from rasid.languages import Direction
from rasid.schemas import DraftResult, ReviewIssue

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Plant:
    name: str
    article: str
    draft: str
    direction: Direction
    omit: str  # removed from the translation
    swap: tuple[str, str]  # (correct, wrong) grammar or attribution error
    omission_found: re.Pattern  # matched against source_span + explanation of an issue
    swap_found: str  # must appear in the issue's target_span


CASES = [
    Plant(
        name="en->ar",
        article="002.txt",
        draft="002.json",
        direction=Direction("en", "ar"),
        omit=" وأصاب خمسة آخرين",  # "and wounded five others"
        swap=(
            "وقالت المدعية العامة لولاية آيوا",
            "وقال المدعية العامة لولاية آيوا",
        ),  # masc. verb, fem. subject
        omission_found=re.compile(r"wounded|five others|injur", re.IGNORECASE),
        swap_found="وقال المدعية",
    ),
    Plant(
        name="ar->ms",
        article="003.txt",
        draft="003_ms.json",
        direction=Direction("ar", "ms"),
        omit=", manakala Iran tidak hadir atas sebab logistik",  # "while Iran was absent for logistical reasons"
        swap=(
            "Mohamed Khaled menjelaskan bahawa",
            "Mohamed Khaled mengakui bahawa",
        ),  # "explained" -> "admitted"
        omission_found=re.compile(
            r"غابت|لوجستي|logistic|absent|absence", re.IGNORECASE
        ),
        swap_found="mengakui",
    ),
]


def plant(case: Plant) -> tuple[str, DraftResult]:
    draft = DraftResult.model_validate_json(
        (ROOT / "runs" / case.draft).read_text(encoding="utf-8")
    )
    text = draft.translation
    for needle in (case.omit, case.swap[0]):
        if text.count(needle) != 1:
            sys.exit(f"{case.name}: expected exactly one {needle!r} in {case.draft}")
    text = text.replace(case.omit, "", 1).replace(*case.swap, 1)
    return text, draft


def caught_omission(issue: ReviewIssue, case: Plant) -> bool:
    return issue.severity in ("critical", "major") and bool(
        case.omission_found.search(f"{issue.source_span} {issue.explanation}")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=5)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    jobs = []
    for case in CASES:
        article = (ROOT / "evals" / "articles" / case.article).read_text(
            encoding="utf-8"
        )
        planted, draft = plant(case)
        checks = pipeline.check_pass(
            article, draft, case.direction, translation=planted
        )
        print(
            f"== {case.name}: deterministic checks on the planted translation\n{format_checks(checks)}\n"
        )
        jobs += [(case, article, planted) for _ in range(args.attempts)]

    def review(job):
        case, article, planted = job
        return pipeline.review_pass(article, planted, case.direction)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(review, jobs))

    report = {}
    for case in CASES:
        runs = [
            (r, u) for (c, _, _), (r, u) in zip(jobs, results, strict=True) if c is case
        ]
        omission_hits = [
            any(caught_omission(i, case) for i in r.issues) for r, _ in runs
        ]
        swap_hits = [
            any(case.swap_found in i.target_span for i in r.issues) for r, _ in runs
        ]
        passed = sum(omission_hits) >= 4 * args.attempts / 5
        print(
            f"== {case.name}: omission caught (critical/major) {sum(omission_hits)}/{len(runs)}, "
            f"grammar/attribution caught {sum(swap_hits)}/{len(runs)}, "
            f"issues per attempt {[len(r.issues) for r, _ in runs]} -> {'PASS' if passed else 'FAIL'}"
        )
        report[case.name] = {
            "omission_caught": omission_hits,
            "swap_caught": swap_hits,
            "passed": passed,
            "attempts": [
                {"issues": [i.model_dump() for i in r.issues], "usage": u.model_dump()}
                for r, u in runs
            ],
        }

    out = ROOT / "runs" / "reviewer_plant_test.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()
