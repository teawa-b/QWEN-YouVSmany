from youvsmany.agents.repetition import is_repetitive, similarity


def test_identical_is_max_similar():
    assert similarity("the case breaks on texture", "the case breaks on texture") > 0.95


def test_distinct_is_low():
    assert similarity(
        "tradition demands the original form",
        "the cost per accepted clip is too high",
    ) < 0.3


def test_is_repetitive_flag():
    prior = ["pineapple ruins the texture balance of the slice"]
    assert is_repetitive("pineapple ruins the texture balance of the slice now", prior, 0.6)
    assert not is_repetitive("cats value independence above all", prior, 0.6)
