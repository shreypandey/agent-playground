from __future__ import annotations

import unittest

from fit_check_agent.context_cleaner import deterministic_product_context


class ContextCleanerTests(unittest.TestCase):
    def test_deterministic_context_keeps_size_and_tooltip_texts(self) -> None:
        cleaned = deterministic_product_context(
            {
                "url": "https://example.com/product",
                "title": "Example product",
                "description_text": "global nav garbage",
                "metadata": {
                    "og:title": "Example OG title",
                    "viewport": "ignore",
                },
                "product_text_blocks": ["Pure cotton T-shirt", "Regular fit"],
                "size_texts": ["S", "M", "L", "Size & Fit The model is 6 feet"],
                "size_chart": {
                    "source": "window.__myx.pdpData",
                    "disclaimer": "Garment Measurements in",
                    "image_url": "https://example.com/size-chart.png",
                    "rows": [
                        {
                            "label": "M",
                            "measurements": [
                                {"name": "Chest", "value": "40.0", "unit": "Inches"}
                            ],
                        }
                    ],
                },
                "tooltip_texts": ["Tap to select size M", "Return within 14 days"],
                "variant_texts": ["Blue", "White"],
                "image_candidates": ["https://example.com/image.jpg"],
            }
        )

        self.assertEqual(cleaned["source_url"], "https://example.com/product")
        self.assertEqual(cleaned["metadata"], {"og:title": "Example OG title"})
        self.assertIn("M", cleaned["size_texts"])
        self.assertEqual(cleaned["size_chart"]["rows"][0]["label"], "M")
        self.assertIn("Tap to select size M", cleaned["tooltip_texts"])
        self.assertNotIn("description_text", cleaned)
        self.assertNotIn("image_candidates", cleaned)


if __name__ == "__main__":
    unittest.main()
