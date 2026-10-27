from app import pdf_parse


def test_title_keeps_short_third_line(tmp_path, sample_pdf):
    path = tmp_path / "paper.pdf"
    path.write_bytes(sample_pdf)
    parsed = pdf_parse.parse_pdf(path)
    assert "A Practical Guide" in parsed["title"]
    assert "Community Garden" in parsed["title"]
    assert "Planning" in parsed["title"]
    assert parsed["blocks"][0]["kind"] == "title"


def test_sentence_split_protects_abbrev_and_decimals():
    text = ("We use e.g. GPT-4.5 and Fig. 3. The value is 3.14. "
            "Experiments show gains. Results are stable.")
    sentences = pdf_parse.split_sentences(text)
    assert "e.g." in sentences[0]
    assert "3.14" in sentences[1] or "3.14" in sentences[0]
    assert len(sentences) >= 3


def test_normalize_block_joins_hyphenated_lines():
    assert pdf_parse.normalize_block("self-\nevolving\n\nagent") == "selfevolving agent"
