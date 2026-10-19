from rasid.checks import (
    check_fact_table,
    check_glossary,
    check_length_ratio,
    check_numbers,
    extract_numbers,
    run_checks,
)
from rasid.glossary import GlossaryEntry
from rasid.languages import Direction
from rasid.schemas import DraftResult, FactItem

MS_TO_AR = Direction("ms", "ar")
EN_TO_AR = Direction("en", "ar")
AR_TO_EN = Direction("ar", "en")
AR_TO_MS = Direction("ar", "ms")

GLOSSARY = [
    GlossaryEntry("MINDEF", "ms", "وزارة الدفاع الماليزية"),
    GlossaryEntry("Ministry of Defence", "en", "وزارة الدفاع الماليزية"),
    GlossaryEntry("kebuntuan", "ms", "مأزق"),
    GlossaryEntry("deadlock", "en", "مأزق"),
    GlossaryEntry("impasse", "en", "مأزق"),
    GlossaryEntry("Strait of Malacca", "en", "مضيق ملقا"),
    GlossaryEntry("Selat Melaka", "ms", "مضيق ملقا"),
]


def draft(translation: str, facts: list[tuple[str, str, str]] = ()) -> DraftResult:
    return DraftResult(
        detected_source_lang="ms",
        title="t",
        summary="s",
        translation=translation,
        facts=[FactItem(kind=k, source=s, target=t) for k, s, t in facts],
        flags=[],
        significance_draft="",
        source_type="news_report",
    )


# --- extract_numbers ---------------------------------------------------------


def test_extract_numbers_handles_digits_commas_and_decimals():
    assert extract_numbers("RM21.2 bilion, 1,456 syarikat, 62 negara") == {
        "21.2": 1,
        "1456": 1,
        "62": 1,
    }
    assert extract_numbers("١٤٥٦ شركة و٦٢ دولة و٢١٫٥") == {
        "1456": 1,
        "62": 1,
        "21.5": 1,
    }
    assert extract_numbers("ends in 2026.") == {
        "2026": 1
    }  # sentence full stop is not a decimal point


# --- check_numbers -----------------------------------------------------------


def test_numbers_pass_with_arabic_indic_digits():
    result = check_numbers("1456 companies from 62 countries", "١٤٥٦ شركة من ٦٢ دولة")
    assert result.passed


def test_numbers_pass_with_comma_thousands_and_percent_spacing():
    assert check_numbers(
        "مشاركة 1456 شركة و80 % من الواردات", "1,456 companies and 80 per cent"
    ).passed


def test_numbers_rm_bilion():
    assert check_numbers(
        "peruntukan RM21.2 bilion", "مخصصات بقيمة 21.2 مليار رينغيت"
    ).passed
    result = check_numbers("peruntukan RM21.2 bilion", "مخصصات بقيمة 21.3 مليار رينغيت")
    assert not result.passed
    assert result.details == ["missing from translation: 21.2", "not in source: 21.3"]


def test_numbers_fail_on_omitted_number_to_arabic():
    source = "Serangan pada 13 Julai mengorbankan 12 orang dan mencederakan lebih 300 yang lain."
    translation = "أسفر الهجوم في 13 يوليو عن مقتل 12 شخصاً وإصابة آخرين."  # 300 dropped
    result = check_numbers(source, translation)
    assert not result.passed
    assert result.details == ["missing from translation: 300"]


def test_numbers_fail_on_added_number_from_arabic():
    # Real case: a bracketed gloss in an Arabic -> English draft added an extra "2026".
    source = "معرض آسيا لخدمات الدفاع والأمن 2026"
    translation = (
        "DSA & NATSEC Asia 2026 (Asia Defence and Security Services Exhibition 2026)"
    )
    result = check_numbers(source, translation)
    assert not result.passed
    assert result.details == ["not in source: 2026"]


def test_numbers_count_repeats():
    result = check_numbers("2026 dan 2026", "2026")
    assert not result.passed
    assert result.details == ["missing from translation: 2026"]


# --- check_glossary ----------------------------------------------------------


def test_glossary_to_arabic_pass_and_fail():
    source = "Kenyataan MINDEF menyebut kebuntuan itu."
    assert check_glossary(
        source, "وأشار بيان وزارة الدفاع الماليزية إلى المأزق", GLOSSARY, MS_TO_AR
    ).passed
    result = check_glossary(
        source, "وأشار بيان وزارة الدفاع إلى الانسداد", GLOSSARY, MS_TO_AR
    )
    assert not result.passed
    assert result.details == [
        "MINDEF → expected وزارة الدفاع الماليزية",
        "kebuntuan → expected مأزق",
    ]


def test_glossary_from_arabic_accepts_any_listed_alternative():
    source = "وأكدت وزارة الدفاع الماليزية أن المحادثات في مأزق"
    translation = "The Ministry of Defence said talks had reached an impasse."
    assert check_glossary(source, translation, GLOSSARY, AR_TO_EN).passed


def test_glossary_from_arabic_fails_on_wrong_form():
    source = "مضيق ملقا"
    result = check_glossary(source, "the Strait of Melaka", GLOSSARY, AR_TO_EN)
    assert not result.passed
    assert result.details == ["مضيق ملقا → expected Strait of Malacca"]
    assert check_glossary(source, "Selat Melaka", GLOSSARY, AR_TO_MS).passed


def test_glossary_with_no_terms_passes():
    result = check_glossary(
        "Eight US states sued.", "رفعت ثماني ولايات دعاوى.", GLOSSARY, EN_TO_AR
    )
    assert result.passed
    assert result.details == ["no glossary terms in source"]


# --- check_length_ratio ------------------------------------------------------


def test_length_ratio_within_band():
    assert check_length_ratio("a " * 100, "ب " * 90, MS_TO_AR).passed
    assert check_length_ratio("ب " * 100, "a " * 130, AR_TO_EN).passed


def test_length_ratio_too_short_to_arabic_suggests_omission():
    result = check_length_ratio("a " * 100, "ب " * 40, MS_TO_AR)
    assert not result.passed
    assert "possible omission" in result.details[0]


def test_length_ratio_too_long_from_arabic_suggests_addition():
    result = check_length_ratio("ب " * 100, "a " * 250, AR_TO_EN)
    assert not result.passed
    assert "possible addition" in result.details[0]


def test_length_ratio_bands_are_per_direction():
    # 1.5 is normal from Arabic but too long into Arabic.
    assert check_length_ratio("ب " * 100, "a " * 150, AR_TO_MS).passed
    assert not check_length_ratio("a " * 100, "ب " * 150, EN_TO_AR).passed


def test_length_ratio_empty_source():
    assert not check_length_ratio("", "x", MS_TO_AR).passed


# --- check_fact_table --------------------------------------------------------


def test_fact_table_to_arabic_ignores_diacritics_and_digit_style():
    d = draft(
        "أطلق مسلح يبلغ ٢٠ عاماً النار فقتل بالغين في جامعة ولاية فلوريدا",
        [("number", "20-year-old", "20 عاماً"), ("number", "two adults", "بالغَين")],
    )
    assert check_fact_table(d, d.translation, EN_TO_AR).passed


def test_fact_table_from_arabic_handles_punctuation_and_line_breaks():
    d = draft(
        "the Association of Southeast Asian Nations (ASEAN) and the Strait of\nMalacca",
        [
            (
                "organisation",
                "رابطة آسيان",
                "Association of Southeast Asian Nations (ASEAN)",
            ),
            ("place", "مضيق ملقا", "Strait of Malacca"),
        ],
    )
    assert check_fact_table(d, d.translation, AR_TO_EN).passed


def test_fact_table_to_arabic_ignores_quotes_and_lil_contraction():
    # Real false alarms from an English -> Arabic draft.
    d = draft(
        "أدلى المتحدث باسم «أوبن إيه آي» ببيان أمام المحكمة الاتحادية للمنطقة الشمالية من كاليفورنيا",
        [
            ("rank", "OpenAI spokesperson", "المتحدث باسم أوبن إيه آي"),
            (
                "place",
                "Northern District of California",
                "المنطقة الشمالية من كاليفورنيا",
            ),
        ],
    )
    assert check_fact_table(d, d.translation, EN_TO_AR).passed


def test_fact_table_known_limit_possessive_form():
    # "its chief executive" = رئيسها التنفيذي; matching cannot see الرئيس inside it (camel-tools, Phase 7).
    d = draft(
        "ورئيسها التنفيذي سام ألتمان", [("rank", "chief executive", "الرئيس التنفيذي")]
    )
    assert not check_fact_table(d, d.translation, EN_TO_AR).passed


def test_fact_table_fails_when_fact_missing_from_translation():
    d = draft(
        "Mohamed Khaled Nordin spoke at DSA 2026.",
        [("name", "خالد نور الدين", "Mohamed Khaled Nordin")],
    )
    edited = "The minister spoke at DSA 2026."  # the human's edit removed the name
    result = check_fact_table(d, edited, AR_TO_EN)
    assert not result.passed
    assert "'Mohamed Khaled Nordin'" in result.details[0]


def test_fact_table_latin_needs_whole_words():
    d = draft("Iranian officials", [("place", "إيران", "Iran")])
    assert not check_fact_table(d, d.translation, AR_TO_EN).passed


# --- run_checks --------------------------------------------------------------


def test_run_checks_returns_all_four_and_rechecks_edited_text():
    source = "Kenyataan MINDEF: sebanyak 62 negara telah menyertai."
    d = draft(
        "بيان وزارة الدفاع الماليزية: شاركت 62 دولة.",  # 7 words vs 7 in source
        [("number", "62 negara", "62 دولة")],
    )
    results = run_checks(source, d, MS_TO_AR, GLOSSARY)
    assert [r.name for r in results] == [
        "numbers",
        "glossary",
        "length_ratio",
        "fact_table",
    ]
    assert all(r.passed for r in results)

    edited = run_checks(
        source, d, MS_TO_AR, GLOSSARY, translation="بيان الوزارة: شاركت دول عدة."
    )
    assert {r.name: r.passed for r in edited} == {
        "numbers": False,
        "glossary": False,
        "length_ratio": True,
        "fact_table": False,
    }
