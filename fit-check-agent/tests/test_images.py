from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from fit_check_agent import images as images_module
from fit_check_agent.images import (
    _safe_extension,
    fetch_product_images,
    is_transformed_url,
    select_original_image_urls,
)


MYNTRA_SAMPLE_URLS = [
    # Originals (no transform path segment) — should pass through.
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/zaIiB32R_686fc74de46f4fe69e50a971f53ea33d.jpg",
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/1ilPKwLX_88d75a8be27c4a8d8f44abc40532c71a.jpg",
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/3GTzwNt3_43c75f217b374013a1b5868dcfb4a0d0.jpg",
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/ZI78DCLb_ffb6b8f93acc47c1b05b1fce7efd0732.jpg",
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/u9SlXbK5_8295d25256b5474fa8c93ed35ff037c0.jpg",
    "https://assets.myntassets.com/assets/images/2026/FEBRUARY/5/OL8JdpWj_47d3bc04baa14d2088208b4ef0117a30.jpg",
    "https://assets.myntassets.com/assets/images/2026/MAY/14/sa8SNPqM_131175836cf342e48d40a06076e97083.jpg",
    # Transforms — should be filtered out.
    "https://assets.myntassets.com/h_1440,q_100,w_1080/v1/assets/images/2026/FEBRUARY/5/zaIiB32R_686fc74de46f4fe69e50a971f53ea33d.jpg",
    "https://assets.myntassets.com/h_200,w_200,c_fill,g_auto/h_1440,q_75,w_1080/v1/assets/images/2026/FEBRUARY/5/zaIiB32R_686fc74de46f4fe69e50a971f53ea33d.jpg",
    "https://assets.myntassets.com/f_webp,h_560,q_90,w_420/v1/assets/images/2026/FEBRUARY/13/BUBtc0FT_6f269c54935f4b90ab0a3040362b844e.jpg",
    "https://assets.myntassets.com/h_150,q_75,w_150,c_fill,fl_progressive/assets/images/2026/APRIL/20/PgIlJac4_4cd2271a048d4e7a94f5ef0b2bf4af0f.jpg",
    "https://assets.myntassets.com/f_auto,h_150,q_auto:best,w_112/assets/images/2026/MAY/8/xY4jUG8W_c107c2166f39483a9440e72f9ff5116b.jpg",
]


class IsTransformedUrlTests(unittest.TestCase):
    def test_flags_transformed_paths(self) -> None:
        self.assertTrue(is_transformed_url(MYNTRA_SAMPLE_URLS[7]))
        self.assertTrue(is_transformed_url(MYNTRA_SAMPLE_URLS[8]))
        self.assertTrue(is_transformed_url(MYNTRA_SAMPLE_URLS[9]))
        self.assertTrue(is_transformed_url(MYNTRA_SAMPLE_URLS[10]))
        self.assertTrue(is_transformed_url(MYNTRA_SAMPLE_URLS[11]))

    def test_passes_originals(self) -> None:
        for url in MYNTRA_SAMPLE_URLS[:7]:
            self.assertFalse(is_transformed_url(url), msg=url)

    def test_query_string_commas_ignored(self) -> None:
        self.assertFalse(
            is_transformed_url("https://cdn/a/b.jpg?w=100,h=100"),
        )

    def test_handles_non_string(self) -> None:
        self.assertFalse(is_transformed_url(None))  # type: ignore[arg-type]


class SelectOriginalImageUrlsTests(unittest.TestCase):
    def test_filters_myntra_fixture(self) -> None:
        originals = select_original_image_urls(MYNTRA_SAMPLE_URLS)
        self.assertEqual(originals, MYNTRA_SAMPLE_URLS[:7])

    def test_empty_input(self) -> None:
        self.assertEqual(select_original_image_urls([]), [])


class SafeExtensionTests(unittest.TestCase):
    def test_uses_content_type_mapping(self) -> None:
        self.assertEqual(_safe_extension("https://x/y", "image/webp"), ".webp")
        self.assertEqual(_safe_extension("https://x/y", "image/jpeg; charset=binary"), ".jpg")
        self.assertEqual(_safe_extension("https://x/y", "image/png"), ".png")

    def test_falls_back_to_url_suffix(self) -> None:
        self.assertEqual(_safe_extension("https://cdn/a/b.webp", ""), ".webp")
        self.assertEqual(_safe_extension("https://cdn/a/b.jpeg", ""), ".jpg")

    def test_defaults_to_jpg(self) -> None:
        self.assertEqual(_safe_extension("https://cdn/a/no-ext", ""), ".jpg")


PNG_BODY = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)


def _mock_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/good.png"):
        return httpx.Response(200, content=PNG_BODY, headers={"content-type": "image/png"})
    if path.endswith("/html"):
        return httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html"})
    if path.endswith("/missing"):
        return httpx.Response(404, content=b"")
    return httpx.Response(500)


class FetchProductImagesTests(unittest.TestCase):
    def test_empty_urls_returns_empty(self) -> None:
        async def run() -> list[Path]:
            with tempfile.TemporaryDirectory() as tmp:
                return await fetch_product_images([], target_dir=Path(tmp))

        self.assertEqual(asyncio.run(run()), [])

    def test_downloads_and_skips_non_image(self) -> None:
        transport = httpx.MockTransport(_mock_handler)
        original = images_module.httpx.AsyncClient

        class _PatchedClient(original):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)

        async def run() -> tuple[int, list[str], list[int]]:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                urls = [
                    "https://cdn.example.com/good.png",
                    "https://cdn.example.com/html",
                    "https://cdn.example.com/missing",
                ]
                images_module.httpx.AsyncClient = _PatchedClient
                try:
                    paths = await images_module.fetch_product_images(
                        urls,
                        target_dir=target,
                        max_images=5,
                        max_bytes=10 * 1024 * 1024,
                        request_timeout_seconds=5.0,
                    )
                finally:
                    images_module.httpx.AsyncClient = original
                return (
                    len(paths),
                    [p.name for p in paths],
                    [p.stat().st_size for p in paths],
                )

        count, names, sizes = asyncio.run(run())
        self.assertEqual(count, 1)
        self.assertTrue(names[0].endswith(".png"))
        self.assertGreater(sizes[0], 0)

    def test_respects_max_bytes(self) -> None:
        transport = httpx.MockTransport(_mock_handler)
        original = images_module.httpx.AsyncClient

        class _PatchedClient(original):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)

        async def run() -> int:
            with tempfile.TemporaryDirectory() as tmp:
                images_module.httpx.AsyncClient = _PatchedClient
                try:
                    paths = await images_module.fetch_product_images(
                        ["https://cdn.example.com/good.png"],
                        target_dir=Path(tmp),
                        max_images=5,
                        max_bytes=10,
                        request_timeout_seconds=5.0,
                    )
                finally:
                    images_module.httpx.AsyncClient = original
                return len(paths)

        self.assertEqual(asyncio.run(run()), 0)


if __name__ == "__main__":
    unittest.main()
