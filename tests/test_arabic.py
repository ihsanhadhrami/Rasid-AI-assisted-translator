from rasid.arabic import normalise, to_western_digits


def test_diacritised_and_plain_forms_match():
    assert normalise("وَزَارَةُ الدِّفَاعِ") == normalise("وزارة الدفاع")


def test_tatweel_removed():
    assert normalise("الدفـــاع") == normalise("الدفاع")


def test_alef_ya_ta_marbuta_variants():
    assert normalise("إندونيسيا") == normalise("اندونيسيا")
    assert normalise("مستشفى") == normalise("مستشفي")
    assert normalise("وزارة") == normalise("وزاره")


def test_whitespace_collapsed():
    assert normalise("  مضيق \n  ملقا ") == "مضيق ملقا"


def test_arabic_indic_digits_convert():
    assert to_western_digits("١٤٥٦ شركة و٦٢ دولة") == "1456 شركة و62 دولة"
    assert to_western_digits("۲۰۲۶") == "2026"
    assert to_western_digits("٢١٫٥ و١٬٠٠٠") == "21.5 و1,000"


def test_original_string_is_not_changed():
    original = "وَزَارَةُ الدِّفَاعِ"
    copy = str(original)
    normalise(original)
    assert original == copy
