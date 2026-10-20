"""Unit tests for description-file discovery and parsing in backend.src.media_fetcher."""

from backend.src.media_fetcher import _find_description_item, parse_description_file

_GDOC = "application/vnd.google-apps.document"


class TestFindDescriptionItem:
    def test_matches_misspelled_google_doc(self):
        files = [{"name": "IMG_1.JPG", "mimeType": "image/jpeg"},
                 {"name": "discription.txt", "mimeType": _GDOC}]
        assert _find_description_item(files)["name"] == "discription.txt"

    def test_matches_any_txt_name(self):
        files = [{"name": "notes.TXT", "mimeType": "application/octet-stream"}]
        assert _find_description_item(files)["name"] == "notes.TXT"

    def test_none_when_no_text_file(self):
        assert _find_description_item([{"name": "a.MOV", "mimeType": "video/quicktime"}]) is None


class TestParseDescriptionFile:
    def test_english_first_without_marker_splits_by_script(self, tmp_path):
        path = tmp_path / "d.txt"
        path.write_text(
            "﻿A Nice Pot\r\nFirst line.\r\nSecond line.\r\nTags:\r\n1. clay pot\r\n2. cezve\r\n\r\n\r\n"
            "Красивая турка\r\nПервая строка.\r\nТеги:\r\n1. турка\r\n2. керамика\r\n",
            encoding="utf-8",
        )
        r = parse_description_file(path)
        assert r["title_en"] == "A Nice Pot"
        assert r["description_en"] == "First line.\nSecond line."
        assert r["title_ru"] == "Красивая турка"
        assert r["description_ru"] == "Первая строка."
        assert r["tags_en"] == ["clay pot", "cezve"]
        assert r["tags_ru"] == ["турка", "керамика"]

    def test_russian_first_with_divider_and_comma_tags(self, tmp_path):
        path = tmp_path / "d.txt"
        path.write_text(
            "Заголовок\nТекст.\n13 тегов для Etsy:\nодин, два, три\n___\nENGLISH\nTitle\nBody.\n13 Etsy tags:\na, b\n",
            encoding="utf-8",
        )
        r = parse_description_file(path)
        assert (r["title_ru"], r["description_ru"]) == ("Заголовок", "Текст.")
        assert (r["title_en"], r["description_en"]) == ("Title", "Body.")
        assert r["tags_ru"] == ["один", "два", "три"]
        assert r["tags_en"] == ["a", "b"]

    def test_single_language_has_no_tags(self, tmp_path):
        path = tmp_path / "d.txt"
        path.write_text("Single Block\nBody text.\n", encoding="utf-8")
        r = parse_description_file(path)
        assert r["title_en"] == "Single Block"
        assert r["title_ru"] == ""
        assert r["tags_en"] == []
