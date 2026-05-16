from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fit_check_agent.profiles import ProfileBundle, TextContext
from fit_check_agent.prompt import build_fit_check_prompt


class PromptTests(unittest.TestCase):
    def test_builds_full_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = ProfileBundle(
                name="formal",
                root=Path(temp_dir),
                text_contexts=(
                    TextContext(
                        relative_path="measurements.md",
                        text="Height: 180cm\nChest: 100cm",
                    ),
                ),
                image_paths=(Path(temp_dir) / "front.jpg",),
            )

            prompt = build_fit_check_prompt(
                profile_bundle=bundle,
                product_payload={
                    "url": "https://example.com/product",
                    "title": "Blue linen shirt",
                    "selected_text": "Size: M",
                },
                profile_image_count=1,
                product_image_count=2,
            )

            self.assertIn("Profile: formal", prompt)
            self.assertIn("Profile images attached: 1", prompt)
            self.assertIn("Product images attached: 2", prompt)
            self.assertIn("Size recommendation", prompt)
            self.assertIn("Closest chart value", prompt)
            self.assertIn("Fit analysis", prompt)
            self.assertIn("Color and styling", prompt)
            self.assertIn("Practical risks", prompt)
            self.assertIn("Better alternative", prompt)
            self.assertIn("Verdict", prompt)
            self.assertIn("profile/formal/measurements.md", prompt)
            self.assertIn("Blue linen shirt", prompt)
            self.assertNotIn("chain-of-thought", prompt)
            self.assertNotIn("Context cleanup:", prompt)
            self.assertNotIn("Product image source URLs", prompt)
            # New invariants from the prompt review.
            self.assertIn("First, generate the try-on image", prompt)
            self.assertIn("output sections 1-6 always", prompt)
            self.assertIn("Include section 7 only when the verdict", prompt)
            self.assertIn("If you cannot see the product image attachments", prompt)
            self.assertIn("If no overlapping measurements exist", prompt)
            self.assertIn("If a size is already selected", prompt)
            self.assertIn("Inspect the product images directly for", prompt)
            self.assertIn(
                "I cannot do this because the product image is missing.",
                prompt,
            )

    def test_short_circuits_when_no_product_images(self) -> None:
        bundle = ProfileBundle(
            name="minimal",
            root=Path("/tmp/minimal"),
            text_contexts=(),
            image_paths=(),
        )

        prompt = build_fit_check_prompt(
            profile_bundle=bundle,
            product_payload={"description_text": "x" * 200},
            profile_image_count=0,
            product_image_count=0,
        )

        self.assertIn(
            "I cannot do this because the product image is missing.",
            prompt,
        )
        self.assertNotIn("Size recommendation", prompt)
        self.assertNotIn("x" * 200, prompt)

    def test_keeps_full_product_context_when_images_attached(self) -> None:
        bundle = ProfileBundle(
            name="minimal",
            root=Path("/tmp/minimal"),
            text_contexts=(),
            image_paths=(),
        )

        prompt = build_fit_check_prompt(
            profile_bundle=bundle,
            product_payload={"description_text": "x" * 200},
            profile_image_count=0,
            product_image_count=1,
        )

        self.assertIn("x" * 200, prompt)


if __name__ == "__main__":
    unittest.main()
