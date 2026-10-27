from app import course


def test_build_units_keeps_short_sections():
    doc = {
        "blocks": [
            {"i": 0, "kind": "heading", "text": "I. INTRODUCTION"},
            {"i": 1, "kind": "para", "text": "short intro"},
            {"i": 2, "kind": "heading", "text": "II. METHOD"},
            {"i": 3, "kind": "para", "text": "method body"},
        ]
    }
    units = course.build_units(doc)
    assert len(units) == 2
    assert units[0]["title"] == "INTRODUCTION"
    assert units[1]["title"] == "METHOD"


def test_bank_crud_and_dedup(tmp_path):
    path = tmp_path / "bank.tsv"
    rows = [
        {"word": "compost", "meaning_cn": "堆肥"},
        {"word": "Compost", "meaning_cn": "重复"},
        {"word": "harvest", "meaning_cn": "收获"},
    ]
    assert course.add_bank_rows(path, rows) == 2
    assert [r["word"] for r in course.read_bank(path)] == ["compost", "harvest"]

    row = course.update_bank_row(path, "compost", {"note": "重点"})
    assert row is not None
    assert row["note"] == "重点"
    assert course.read_bank(path)[0]["note"] == "重点"

    assert course.remove_bank_rows(path, ["harvest"]) == 1
    assert [r["word"] for r in course.read_bank(path)] == ["compost"]


def test_lesson_rows_skip_invalid_vocab():
    lesson = {"vocab": [
        {"word": "compost", "meaning_cn": "堆肥"},
        {"meaning_cn": "缺单词"},
        "bad",
    ]}
    rows = course.lesson_rows(lesson, "doc/unit001")
    assert len(rows) == 1
    assert rows[0]["source"] == "doc/unit001"
