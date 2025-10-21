from ce_bridge_service.normalization import PartNumberNormalizer


def test_normalizer_applies_rules_in_order():
    normalizer = PartNumberNormalizer()
    result = normalizer.normalize(" sn74ahc1g08-tr ")
    assert result.normalized == "SN74AHC1G08"
    assert result.rule_ids == [
        "rule.case_fold",
        "rule.strip_suffix.-TR",
        "rule.strip_punct",
    ]
    assert result.descriptions == [
        "uppercased input",
        "ignored suffix '-TR'",
        "removed punctuation",
    ]


def test_normalizer_removes_suffixes_sequentially():
    normalizer = PartNumberNormalizer()
    result = normalizer.normalize("pn-tr-tr")
    assert result.normalized == "PN"
    assert result.rule_ids == [
        "rule.case_fold",
        "rule.strip_suffix.-TR",
        "rule.strip_suffix.-TR",
    ]


def test_normalizer_strips_unicode_punctuation():
    normalizer = PartNumberNormalizer()
    result = normalizer.normalize("PN\u00A0100–A")
    assert result.normalized == "PN100A"
    assert result.rule_ids == ["rule.strip_punct"]


def test_merge_descriptions_preserves_unique_order():
    normalizer = PartNumberNormalizer()
    first = normalizer.normalize("pn-100-tr")
    second = normalizer.normalize("pn-100/TP")
    merged = PartNumberNormalizer.merge_descriptions(first, second)
    assert merged == [
        "uppercased input",
        "ignored suffix '-TR'",
        "removed punctuation",
        "ignored suffix '/TP'",
    ]
