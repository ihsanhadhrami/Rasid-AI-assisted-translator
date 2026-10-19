"""One glossary file serves both directions: Malay/English term <-> required Arabic form."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from rasid.arabic import normalise, to_western_digits
from rasid.languages import NAMES

# Optional `direction` column: which translation direction a row applies to.
DIRECTIONS = {"both", "to_ar", "from_ar"}


@dataclass(frozen=True)
class GlossaryEntry:
    source_term: str  # the Malay or English term
    source_lang: str  # "ms" or "en"
    arabic: str
    notes: str = ""
    direction: str = (
        "both"  # "both", "to_ar" (ms/en -> ar only) or "from_ar" (ar -> ms/en only)
    )

    def applies(self, target_lang: str) -> bool:
        return self.direction == "both" or self.direction == (
            "to_ar" if target_lang == "ar" else "from_ar"
        )


@dataclass(frozen=True)
class GlossaryHit:
    found: str  # the form found in the source text
    accepted: tuple[str, ...]  # any one of these in the translation satisfies the check
    notes: str = ""


def load_glossary(path: Path) -> list[GlossaryEntry]:
    # utf-8-sig tolerates the BOM that Excel adds when saving CSV
    entries = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("source_term") or "").strip()
            if not term:
                continue
            where = f"{path.name} line {reader.line_num}"
            arabic = (row.get("arabic") or "").strip()
            if not arabic:
                raise ValueError(
                    f"{where}: no Arabic form for {term!r}. "
                    "Use commas between columns and quote fields that contain commas."
                )
            direction = (row.get("direction") or "").strip() or "both"
            if direction not in DIRECTIONS:
                raise ValueError(
                    f"{where}: direction must be blank, both, to_ar or from_ar, not {direction!r}"
                )
            entries.append(
                GlossaryEntry(
                    source_term=term,
                    source_lang=(row.get("source_lang") or "").strip(),
                    arabic=arabic,
                    notes=(row.get("notes") or "").strip(),
                    direction=direction,
                )
            )
    return entries


_QUOTES = re.compile("[«»\"“”„'‘’]")
_LIL = re.compile(r"(?<!\S)لل")  # ل + ال contracts to لل: للمنطقة = ل + المنطقة


def _arabic_key(text: str) -> str:
    """Matching form: normalised, Western digits, no quotation marks, لل expanded back to ال."""
    text = _QUOTES.sub("", to_western_digits(text))
    return normalise(_LIL.sub("ال", text))


def term_in_text(term: str, text: str, arabic: bool) -> bool:
    """Arabic: normalised substring (clitics attach to words, so no word boundary).
    Malay/English: case-insensitive, whole words, any run of whitespace between words."""
    if arabic:
        return _arabic_key(term) in _arabic_key(text)
    words = r"\s+".join(re.escape(w) for w in term.split())
    if not words:
        return False
    # Lookarounds instead of \b, so terms that start or end with punctuation still match.
    return re.search(rf"(?<!\w){words}(?!\w)", text, re.IGNORECASE) is not None


def _by_arabic(
    entries: list[GlossaryEntry], target_lang: str
) -> dict[str, list[GlossaryEntry]]:
    """Rows usable when translating from Arabic into `target_lang`, grouped by Arabic form."""
    groups: dict[str, list[GlossaryEntry]] = {}
    for e in entries:
        if e.source_lang == target_lang and e.applies(target_lang):
            groups.setdefault(e.arabic, []).append(e)
    return groups


def _join_notes(group: list[GlossaryEntry]) -> str:
    return "; ".join(dict.fromkeys(e.notes for e in group if e.notes))


def find_hits(
    text: str, entries: list[GlossaryEntry], source_lang: str, target_lang: str
) -> list[GlossaryHit]:
    """Glossary terms present in the source, with the target forms the translation must use."""
    if target_lang == "ar":
        # dict.fromkeys drops duplicates, e.g. "Houthi" listed under both ms and en
        return list(
            dict.fromkeys(
                GlossaryHit(e.source_term, (e.arabic,), e.notes)
                for e in entries
                if e.applies("ar") and term_in_text(e.source_term, text, arabic=False)
            )
        )
    # From Arabic: only rows in the target language can be enforced.
    return [
        GlossaryHit(arabic, tuple(e.source_term for e in group), _join_notes(group))
        for arabic, group in _by_arabic(entries, target_lang).items()
        if term_in_text(arabic, text, arabic=True)
    ]


def format_for_prompt(
    entries: list[GlossaryEntry], source_lang: str, target_lang: str
) -> str:
    """Markdown table oriented for the direction."""
    if target_lang == "ar":
        lines = [
            "| Source term | Lang | Required Arabic | Notes |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {e.source_term} | {e.source_lang} | {e.arabic} | {e.notes} |"
            for e in entries
            if e.applies("ar")
        ]
        return "\n".join(lines)
    lines = [f"| Arabic | Required {NAMES[target_lang]} | Notes |", "|---|---|---|"]
    lines += [
        f"| {arabic} | {' / '.join(e.source_term for e in group)} | {_join_notes(group)} |"
        for arabic, group in _by_arabic(entries, target_lang).items()
    ]
    return "\n".join(lines)
