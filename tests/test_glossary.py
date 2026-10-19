import pytest

from rasid.config import DATA_DIR, ROOT
from rasid.glossary import (
    GlossaryEntry,
    find_hits,
    format_for_prompt,
    load_glossary,
    term_in_text,
)

ENTRIES = [
    GlossaryEntry("MINDEF", "ms", "وزارة الدفاع الماليزية"),
    GlossaryEntry("Ministry of Defence", "en", "وزارة الدفاع الماليزية"),
    GlossaryEntry("TLDM", "ms", "البحرية الملكية الماليزية"),
    GlossaryEntry("Wisma Putra", "ms", "وزارة الخارجية الماليزية"),
    GlossaryEntry("deadlock", "en", "مأزق", "Not انسداد"),
    GlossaryEntry("impasse", "en", "مأزق", "Not انسداد"),
]


def test_load_real_glossary():
    entries = load_glossary(DATA_DIR / "glossary.csv")
    assert entries
    assert all(e.source_term and e.arabic for e in entries)


def test_load_rejects_bad_direction(tmp_path):
    path = tmp_path / "g.csv"
    path.write_text(
        "source_term,source_lang,arabic,notes,direction\nDSA,en,معرض,,sideways\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2"):
        load_glossary(path)


# --- Direction column --------------------------------------------------------

DIRECTED = [
    GlossaryEntry("DSA", "en", "معرض خدمات الدفاع", direction="from_ar"),
    GlossaryEntry(
        "Defence Services Asia", "en", "معرض خدمات الدفاع", direction="to_ar"
    ),
]


def test_from_ar_row_is_ignored_when_translating_to_arabic():
    # In Malay/English sources "DSA" may be the news site Defence Security Asia.
    assert find_hits("Pada penilaian DSA, persoalan", DIRECTED, "ms", "ar") == []
    hits = find_hits("the Defence Services Asia exhibition", DIRECTED, "en", "ar")
    assert [h.found for h in hits] == ["Defence Services Asia"]


def test_to_ar_row_is_ignored_when_translating_from_arabic():
    hits = find_hits("معرض خدمات الدفاع 2026", DIRECTED, "ar", "en")
    assert [h.accepted for h in hits] == [("DSA",)]
    assert "Defence Services Asia" not in format_for_prompt(DIRECTED, "ar", "en")
    assert "| DSA |" not in format_for_prompt(DIRECTED, "en", "ar")


# --- Real glossary on the eval articles --------------------------------------


def _article(name: str) -> str:
    return (ROOT / "evals" / "articles" / name).read_text(encoding="utf-8")


def test_real_glossary_on_arabic_article_to_english():
    hits = find_hits(
        _article("003.txt"), load_glossary(DATA_DIR / "glossary.csv"), "ar", "en"
    )
    required = {a for h in hits for a in h.accepted}
    assert {
        "Strait of Malacca",
        "Türkiye",
        "Putrajaya Security Forum",
        "Mohammad Nazri",
        "Middle East",
    } <= required


def test_real_glossary_on_malay_article_to_arabic():
    found = {
        h.found
        for h in find_hits(
            _article("001.txt"), load_glossary(DATA_DIR / "glossary.csv"), "ms", "ar"
        )
    }
    assert {"kebuntuan", "Houthi", "DSA"} <= found  # DSA: the news site itself


# --- Malay/English -> Arabic -------------------------------------------------


def test_to_arabic_is_case_insensitive():
    hits = find_hits("Kenyataan mindef hari ini", ENTRIES, "ms", "ar")
    assert [(h.found, h.accepted) for h in hits] == [
        ("MINDEF", ("وزارة الدفاع الماليزية",))
    ]


def test_to_arabic_respects_word_boundaries():
    assert find_hits("TLDMX dan XTLDM", ENTRIES, "ms", "ar") == []
    assert find_hits("kapal TLDM,", ENTRIES, "ms", "ar")[0].found == "TLDM"


def test_to_arabic_multiword_term():
    hits = find_hits("Menurut Wisma Putra semalam", ENTRIES, "ms", "ar")
    assert [h.found for h in hits] == ["Wisma Putra"]


# --- Arabic -> Malay/English -------------------------------------------------


def test_from_arabic_matches_with_clitics_and_diacritics():
    text = "وأكدت وَزَارَةُ الدِّفَاعِ الماليزية أن الوضع في المأزق"
    hits = find_hits(text, ENTRIES, "ar", "en")
    assert {h.found: h.accepted for h in hits} == {
        "وزارة الدفاع الماليزية": ("Ministry of Defence",),
        "مأزق": ("deadlock", "impasse"),
    }


def test_from_arabic_only_enforces_target_language_rows():
    text = "وزارة الخارجية الماليزية ووزارة الدفاع الماليزية"
    to_malay = [h.accepted for h in find_hits(text, ENTRIES, "ar", "ms")]
    assert to_malay == [("MINDEF",), ("Wisma Putra",)]
    # Wisma Putra has no English row, so Arabic -> English can't enforce it.
    to_english = [h.accepted for h in find_hits(text, ENTRIES, "ar", "en")]
    assert to_english == [("Ministry of Defence",)]


def test_from_arabic_no_hits():
    assert find_hits("مضيق ملقا", ENTRIES, "ar", "en") == []


# --- Matching and prompt table -----------------------------------------------


def test_term_in_text():
    assert term_in_text(
        "Ministry of Defence", "the ministry of defence said", arabic=False
    )
    assert not term_in_text("deadlock", "deadlocked", arabic=False)
    assert term_in_text("مأزق", "المأزقَ", arabic=True)


def test_prompt_table_to_arabic_lists_all_rows():
    table = format_for_prompt(ENTRIES, "ms", "ar")
    assert "| MINDEF | ms | وزارة الدفاع الماليزية |  |" in table
    assert table.count("\n") == len(ENTRIES) + 1


def test_prompt_table_from_arabic_groups_alternatives():
    table = format_for_prompt(ENTRIES, "ar", "en")
    assert "| Arabic | Required English | Notes |" in table
    assert "| مأزق | deadlock / impasse | Not انسداد |" in table
    assert "MINDEF" not in table and "Wisma Putra" not in table
