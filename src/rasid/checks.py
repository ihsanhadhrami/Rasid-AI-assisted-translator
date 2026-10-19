"""Deterministic checks (no LLM). Aids for the reviewer: a false alarm is acceptable, a missed error isn't.

Known limits: numbers written as words ("dua", "two", "ثلاثة") and scale words ("bilion" -> "مليار")
are invisible to the number check; the fact table and the reviewer pass cover them.
"""

import re
from collections import Counter

from rasid.arabic import to_western_digits
from rasid.glossary import GlossaryEntry, find_hits, term_in_text
from rasid.languages import Direction
from rasid.schemas import CheckResult, DraftResult

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Expected translation/source word-count ratio. Arabic attaches articles and prepositions
# to words, so translations into Arabic run shorter. Tune both bands on the eval set.
LENGTH_BANDS: dict[str, tuple[float, float]] = {
    "to_ar": (0.5, 1.3),
    "from_ar": (0.8, 2.0),
}


def extract_numbers(text: str) -> Counter:
    """Numbers as a multiset, after converting Arabic-Indic digits and dropping thousands commas."""
    return Counter(n.replace(",", "") for n in NUM_RE.findall(to_western_digits(text)))


def _fmt(counter: Counter) -> str:
    return ", ".join(f"{n} (×{c})" if c > 1 else n for n, c in sorted(counter.items()))


def check_numbers(source: str, translation: str) -> CheckResult:
    src, tgt = extract_numbers(source), extract_numbers(translation)
    missing, added = src - tgt, tgt - src
    details = []
    if missing:
        details.append(f"missing from translation: {_fmt(missing)}")
    if added:
        details.append(f"not in source: {_fmt(added)}")
    if not details:
        details.append(f"{sum(src.values())} numbers match")
    return CheckResult(name="numbers", passed=not (missing or added), details=details)


def check_glossary(
    source: str, translation: str, entries: list[GlossaryEntry], direction: Direction
) -> CheckResult:
    hits = find_hits(source, entries, direction.source, direction.target)
    to_arabic = direction.to_arabic
    missing = [
        h
        for h in hits
        if not any(term_in_text(a, translation, to_arabic) for a in h.accepted)
    ]
    details = [f"{h.found} → expected {' / '.join(h.accepted)}" for h in missing]
    if not details:
        details.append(
            f"{len(hits)} glossary terms used correctly"
            if hits
            else "no glossary terms in source"
        )
    return CheckResult(name="glossary", passed=not missing, details=details)


def check_length_ratio(
    source: str,
    translation: str,
    direction: Direction,
    bands: dict[str, tuple[float, float]] = LENGTH_BANDS,
) -> CheckResult:
    low, high = bands["to_ar" if direction.to_arabic else "from_ar"]
    src_words, tgt_words = len(source.split()), len(translation.split())
    if src_words == 0:
        return CheckResult(
            name="length_ratio", passed=False, details=["source is empty"]
        )
    ratio = tgt_words / src_words
    passed = low <= ratio <= high
    detail = f"ratio {ratio:.2f} ({tgt_words}/{src_words} words), expected {low}–{high}"
    if not passed:
        detail += ": possible " + ("omission" if ratio < low else "addition")
    return CheckResult(name="length_ratio", passed=passed, details=[detail])


def check_fact_table(
    draft: DraftResult, translation: str, direction: Direction
) -> CheckResult:
    """Every fact-table target must appear in the translation (which the human may have edited)."""
    absent = [
        f
        for f in draft.facts
        if not term_in_text(f.target, translation, direction.to_arabic)
    ]
    details = [
        f"{f.kind}: {f.target!r} (source {f.source!r}) not found in translation"
        for f in absent
    ]
    if not details:
        details.append(f"all {len(draft.facts)} facts found in translation")
    return CheckResult(name="fact_table", passed=not absent, details=details)


def run_checks(
    source: str,
    draft: DraftResult,
    direction: Direction,
    entries: list[GlossaryEntry],
    translation: str | None = None,
) -> list[CheckResult]:
    """All four checks. `translation` defaults to the draft's; pass the human's edited text to recheck it."""
    text = draft.translation if translation is None else translation
    return [
        check_numbers(source, text),
        check_glossary(source, text, entries, direction),
        check_length_ratio(source, text, direction),
        check_fact_table(draft, text, direction),
    ]


def format_checks(results: list[CheckResult]) -> str:
    return "\n".join(
        f"{'✅' if r.passed else '❌'} {r.name}: " + "; ".join(r.details)
        for r in results
    )
