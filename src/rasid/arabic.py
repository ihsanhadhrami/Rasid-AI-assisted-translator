"""Arabic normalisation for matching. Never show normalised text to the user."""

import re

TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def to_western_digits(text: str) -> str:
    return text.translate(DIGITS).replace("٫", ".").replace("٬", ",")


def normalise(text: str) -> str:
    """For matching only. Never show normalised text to the user."""
    text = TASHKEEL.sub("", text).replace("ـ", "")  # diacritics, tatweel
    text = re.sub("[إأآٱ]", "ا", text)  # alef variants
    text = text.replace("ى", "ي").replace("ة", "ه")  # ya / ta marbuta
    return re.sub(r"\s+", " ", text).strip()
