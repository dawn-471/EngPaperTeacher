import pytest

from app import chunking


def test_chunk_text_covers_words():
    try:
        chunking._get_nlp()
    except Exception as e:  # noqa: BLE001
        pytest.skip("spaCy model unavailable: %s" % e)
    text = "We turn kitchen scraps into compost for the community garden."
    chunks = chunking.chunk_text(text)
    assert chunks
    joined = " ".join(c["text"] for c in chunks)
    assert "kitchen scraps" in joined
    assert "community garden" in joined
    for c in chunks:
        assert c["start"] < c["end"]
        assert c["label"]
