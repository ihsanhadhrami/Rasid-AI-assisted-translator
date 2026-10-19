"""Language codes, script detection and the allowed translation directions."""

import re
from dataclasses import dataclass
from typing import Literal

Lang = Literal["ms", "en", "ar"]

NAMES: dict[str, str] = {"ms": "Malay", "en": "English", "ar": "Arabic"}
VALID_PAIRS = {("ms", "ar"), ("en", "ar"), ("ar", "ms"), ("ar", "en")}

_ARABIC_LETTER = re.compile(r"[ؠ-يٮ-ۓۺ-ۿݐ-ݿﭐ-﷿ﹰ-ﻼ]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")


class DirectionError(ValueError):
    pass


def detect_script(text: str) -> Literal["ar", "latin"]:
    """'ar' if most letters are Arabic, else 'latin'."""
    arabic = len(_ARABIC_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    return "ar" if arabic > latin else "latin"


@dataclass(frozen=True)
class Direction:
    source: str  # "ms", "en", "ar", or "auto" (Malay or English, decided by the model)
    target: Lang

    @property
    def to_arabic(self) -> bool:
        return self.target == "ar"

    @property
    def source_name(self) -> str:
        return NAMES.get(self.source, "Malay or English")

    @property
    def target_name(self) -> str:
        return NAMES[self.target]

    def __str__(self) -> str:
        return f"{self.source}->{self.target}"


def resolve_direction(
    text: str, source_lang: str = "auto", target_lang: str | None = None
) -> Direction:
    """Pick the translation direction. Arabic is detected from the script; Malay vs English is not."""
    script = detect_script(text)
    if source_lang == "auto":
        source = "ar" if script == "ar" else "auto"
    elif source_lang not in NAMES:
        raise DirectionError(
            f"Unknown source language {source_lang!r}; use auto, ms, en or ar"
        )
    elif (source_lang == "ar") != (script == "ar"):
        looks = "Arabic" if script == "ar" else "Latin-script (Malay/English)"
        raise DirectionError(
            f"Source language is {source_lang!r} but the text looks {looks}"
        )
    else:
        source = source_lang

    if source == "ar":
        target = target_lang or "ms"  # default reader: Malaysian officials
        if target not in ("ms", "en"):
            raise DirectionError(
                "Arabic sources translate into Malay (ms) or English (en)"
            )
    else:
        target = target_lang or "ar"
        if target != "ar":
            raise DirectionError(
                "Malay and English sources translate into Arabic (ar) only"
            )
    return Direction(source, target)
