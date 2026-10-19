import pytest

from rasid.languages import DirectionError, detect_script, resolve_direction

ARABIC = "استبعد وزير الدفاع الماليزي خالد نور الدين أن يواجه مضيق ملقا وضعا مشابها"
MALAY = "Perdana Menteri Israel dilaporkan sedang mendapatkan persetujuan Arab Saudi"
ENGLISH = "Eight US states have filed the most significant coordinated action"


def test_detect_script():
    assert detect_script(ARABIC) == "ar"
    assert detect_script(MALAY) == "latin"
    assert detect_script(ENGLISH) == "latin"


def test_detect_script_mixed_follows_majority():
    assert detect_script(ARABIC + " (Deep Fake) 2026") == "ar"
    assert detect_script(ENGLISH + " مضيق") == "latin"


@pytest.mark.parametrize(
    ("text", "src", "tgt", "expected"),
    [
        (MALAY, "auto", None, "auto->ar"),
        (MALAY, "ms", None, "ms->ar"),
        (ENGLISH, "en", "ar", "en->ar"),
        (ARABIC, "auto", None, "ar->ms"),
        (ARABIC, "ar", "en", "ar->en"),
        (ARABIC, "auto", "ms", "ar->ms"),
    ],
)
def test_valid_directions(text, src, tgt, expected):
    assert str(resolve_direction(text, src, tgt)) == expected


@pytest.mark.parametrize(
    ("text", "src", "tgt"),
    [
        (MALAY, "ms", "en"),  # Malay <-> English is out of scope
        (ENGLISH, "auto", "ms"),
        (ARABIC, "ar", "ar"),
        (ARABIC, "ms", None),  # declared language contradicts the script
        (MALAY, "ar", "en"),
        (MALAY, "fr", None),
    ],
)
def test_invalid_directions(text, src, tgt):
    with pytest.raises(DirectionError):
        resolve_direction(text, src, tgt)
