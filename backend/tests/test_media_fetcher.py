"""Unit tests for backend.src.media_fetcher.

All Google Drive API calls are mocked — no network access required.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from backend.src.media_fetcher import (
    _parse_folder_name,
    _list_items,
    _resolve_root_folder_id,
    fetch_new_products,
    ProductFolder,
    _MAX_IMAGES,
    _MAX_VIDEOS,
)


# ── _parse_folder_name ────────────────────────────────────────────────────────

class TestParseFolderName:
    def test_available_product(self):
        result = _parse_folder_name("20260517_200")
        assert result == {"date_str": "20260517", "price_ils": 200, "is_sold": False}

    def test_sold_product(self):
        result = _parse_folder_name("20250101_100_sold")
        assert result == {"date_str": "20250101", "price_ils": 100, "is_sold": True}

    def test_invalid_name_ignored(self):
        for bad in ["random_folder", "2026_200", "20260517", "20260517_abc", ""]:
            assert _parse_folder_name(bad) is None, f"Expected None for {bad!r}"

    def test_high_price(self):
        result = _parse_folder_name("20260101_9999")
        assert result["price_ils"] == 9999


# ── _list_items ───────────────────────────────────────────────────────────────

class TestListItems:
    def _make_service(self, pages):
        """Build a mock service whose files().list().execute() returns *pages* in order."""
        execute = MagicMock(side_effect=pages)
        list_mock = MagicMock()
        list_mock.return_value.execute = execute
        service = MagicMock()
        service.files.return_value.list = list_mock
        return service

    def test_single_page(self):
        page = {"files": [{"id": "1", "name": "a.jpg", "mimeType": "image/jpeg"}]}
        service = self._make_service([page])
        result = _list_items(service, "parent123")
        assert len(result) == 1
        assert result[0]["name"] == "a.jpg"

    def test_pagination(self):
        page1 = {
            "files": [{"id": "1", "name": "a.jpg", "mimeType": "image/jpeg"}],
            "nextPageToken": "tok1",
        }
        page2 = {"files": [{"id": "2", "name": "b.jpg", "mimeType": "image/jpeg"}]}
        service = self._make_service([page1, page2])
        result = _list_items(service, "parent123")
        assert len(result) == 2

    def test_mime_filter_appended_to_query(self):
        service = self._make_service([{"files": []}])
        _list_items(service, "pid", mime_type="application/vnd.google-apps.folder")
        call_kwargs = service.files.return_value.list.call_args
        assert "application/vnd.google-apps.folder" in call_kwargs.kwargs.get("q", "")


# ── _resolve_root_folder_id ───────────────────────────────────────────────────

class TestResolveRootFolderId:
    def _service_with_folder_search(self, folders):
        execute = MagicMock(return_value={"files": folders})
        list_mock = MagicMock()
        list_mock.return_value.execute = execute
        service = MagicMock()
        service.files.return_value.list = list_mock
        return service

    def test_uses_folder_id_when_set(self):
        service = MagicMock()
        cfg_patch = {
            "folder_id": "explicit_id",
            "folder_name": "Lika_ETSY",
        }
        with patch("backend.src.media_fetcher.CONFIG", {"gdrive": cfg_patch, "currency": {"ils_to_usd_ratio": 0.8}}):
            result = _resolve_root_folder_id(service)
        assert result == "explicit_id"
        service.files.assert_not_called()

    def test_resolves_by_name(self):
        service = self._service_with_folder_search([{"id": "found_id", "name": "Lika_ETSY"}])
        cfg_patch = {"folder_id": "", "folder_name": "Lika_ETSY"}
        with patch("backend.src.media_fetcher.CONFIG", {"gdrive": cfg_patch, "currency": {"ils_to_usd_ratio": 0.8}}):
            result = _resolve_root_folder_id(service)
        assert result == "found_id"

    def test_raises_when_folder_not_found(self):
        service = self._service_with_folder_search([])
        cfg_patch = {"folder_id": "", "folder_name": "Missing"}
        with patch("backend.src.media_fetcher.CONFIG", {"gdrive": cfg_patch, "currency": {"ils_to_usd_ratio": 0.8}}):
            with pytest.raises(RuntimeError, match="not found"):
                _resolve_root_folder_id(service)

    def test_raises_when_nothing_configured(self):
        service = MagicMock()
        cfg_patch = {"folder_id": "", "folder_name": ""}
        with patch("backend.src.media_fetcher.CONFIG", {"gdrive": cfg_patch, "currency": {"ils_to_usd_ratio": 0.8}}):
            with pytest.raises(RuntimeError, match="configured"):
                _resolve_root_folder_id(service)


# ── fetch_new_products ────────────────────────────────────────────────────────

def _make_drive_file(name: str, file_id: str, mime: str = "image/jpeg") -> dict:
    return {"id": file_id, "name": name, "mimeType": mime}


class TestFetchNewProducts:
    """Integration-style tests for fetch_new_products with all I/O mocked."""

    def _run(self, subfolders, files_per_folder, already_processed=None, tmp_dir=None):
        """Helper: run fetch_new_products with a fully mocked Drive service.

        Args:
            subfolders: list of (name, folder_id) tuples representing Drive subfolders
            files_per_folder: dict mapping folder_id → list of file dicts
            already_processed: set of folder names already in state (default empty)
            tmp_dir: base download dir (uses tmpdir if not given)
        """
        already_processed = already_processed or set()

        def mock_list_items(service, parent_id, mime_type=None):
            if mime_type == "application/vnd.google-apps.folder":
                return [{"id": fid, "name": fname, "mimeType": "application/vnd.google-apps.folder"}
                        for fname, fid in subfolders]
            return files_per_folder.get(parent_id, [])

        with tempfile.TemporaryDirectory() as tmpdir:
            base = tmp_dir or tmpdir
            cfg = {
                "gdrive": {
                    "folder_id": "root_id",
                    "folder_name": "Lika_ETSY",
                    "download_dir": base,
                    "supported_image_formats": ["jpg", "jpeg", "png", "webp"],
                    "supported_video_formats": ["mp4", "mov"],
                    "max_images": _MAX_IMAGES,
                    "max_videos": _MAX_VIDEOS,
                },
                "currency": {"ils_to_usd_ratio": 0.8},
            }

            def fake_download(service, file_id, dest_path):
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(b"fake")

            with (
                patch("backend.src.media_fetcher.CONFIG", cfg),
                patch("backend.src.media_fetcher._build_drive_service", return_value=MagicMock()),
                patch("backend.src.media_fetcher._resolve_root_folder_id", return_value="root_id"),
                patch("backend.src.media_fetcher._list_items", side_effect=mock_list_items),
                patch("backend.src.media_fetcher._download_file", side_effect=fake_download),
                patch("backend.src.media_fetcher.is_processed", side_effect=lambda n: n in already_processed),
                patch("backend.src.media_fetcher.upsert_product"),
                patch("backend.src.media_fetcher.log_error"),
            ):
                return fetch_new_products()

    def test_returns_empty_when_no_new_folders(self):
        result = self._run(
            subfolders=[("20260517_200", "fid1")],
            files_per_folder={},
            already_processed={"20260517_200"},
        )
        assert result == []

    def test_skips_non_product_folders(self):
        result = self._run(
            subfolders=[("random_name", "fid1"), ("another", "fid2")],
            files_per_folder={},
        )
        assert result == []

    def test_single_new_product(self):
        files = [_make_drive_file(f"img{i:02d}.jpg", f"img_{i}") for i in range(3)]
        result = self._run(
            subfolders=[("20260517_200", "fid1")],
            files_per_folder={"fid1": files},
        )
        assert len(result) == 1
        pf = result[0]
        assert pf.folder_name == "20260517_200"
        assert pf.price_ils == 200
        assert pf.is_sold is False
        assert len(pf.images) == 3
        assert len(pf.videos) == 0

    def test_sold_product_parsed_correctly(self):
        result = self._run(
            subfolders=[("20250101_150_sold", "fid1")],
            files_per_folder={"fid1": []},
        )
        assert result[0].is_sold is True
        assert result[0].status == "sold"

    def test_image_limit_respected(self):
        # Provide more images than the configured max
        files = [_make_drive_file(f"img{i:02d}.jpg", f"img_{i}") for i in range(_MAX_IMAGES + 5)]
        result = self._run(
            subfolders=[("20260517_200", "fid1")],
            files_per_folder={"fid1": files},
        )
        assert len(result[0].images) == _MAX_IMAGES

    def test_video_limit_respected(self):
        images = [_make_drive_file("photo.jpg", "img_1")]
        videos = [
            _make_drive_file("video1.mp4", "vid_1", "video/mp4"),
            _make_drive_file("video2.mp4", "vid_2", "video/mp4"),
        ]
        result = self._run(
            subfolders=[("20260517_200", "fid1")],
            files_per_folder={"fid1": images + videos},
        )
        assert len(result[0].videos) == _MAX_VIDEOS

    def test_unsupported_files_ignored(self):
        files = [
            _make_drive_file("photo.jpg", "img_1"),
            _make_drive_file("readme.txt", "txt_1", "text/plain"),
            _make_drive_file("clip.mp4", "vid_1", "video/mp4"),
        ]
        result = self._run(
            subfolders=[("20260517_200", "fid1")],
            files_per_folder={"fid1": files},
        )
        assert len(result[0].images) == 1
        assert len(result[0].videos) == 1

    def test_price_usd_conversion(self):
        result = self._run(
            subfolders=[("20260517_100", "fid1")],
            files_per_folder={"fid1": []},
        )
        # 100 ILS × 0.80 = 80 USD
        assert result[0].price_usd == 80

    def test_multiple_new_products(self):
        result = self._run(
            subfolders=[
                ("20260517_200", "fid1"),
                ("20260518_300", "fid2"),
            ],
            files_per_folder={
                "fid1": [_make_drive_file("a.jpg", "img_1")],
                "fid2": [_make_drive_file("b.jpg", "img_2")],
            },
        )
        assert len(result) == 2
        names = {pf.folder_name for pf in result}
        assert names == {"20260517_200", "20260518_300"}
