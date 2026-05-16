from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fit_check_agent.profiles import (
    ProfileError,
    discover_profiles,
    load_profile_bundle,
)


class ProfileTests(unittest.TestCase):
    def test_discovers_visible_profile_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "formal").mkdir()
            (root / "casual").mkdir()
            (root / ".hidden").mkdir()
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            self.assertEqual(discover_profiles(root), ["casual", "formal"])

    def test_loads_supported_text_and_images_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "shrey"
            nested = profile / "photos"
            nested.mkdir(parents=True)
            (profile / "measurements.md").write_text("height: 180cm", encoding="utf-8")
            (nested / "front.jpg").write_bytes(b"fake-image")
            (nested / "ignore.pdf").write_bytes(b"fake-pdf")

            bundle = load_profile_bundle(root, "shrey")

            self.assertEqual(bundle.name, "shrey")
            self.assertEqual(
                [context.relative_path for context in bundle.text_contexts],
                ["measurements.md"],
            )
            self.assertEqual(bundle.text_contexts[0].text, "height: 180cm")
            self.assertEqual([path.name for path in bundle.image_paths], ["front.jpg"])

    def test_rejects_path_traversal_profile_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ProfileError):
                load_profile_bundle(Path(temp_dir), "../secret")

    def test_reads_full_text_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "shrey"
            profile.mkdir()
            (profile / "measurements.txt").write_text("abcdef", encoding="utf-8")

            bundle = load_profile_bundle(root, "shrey")

            self.assertEqual(bundle.text_contexts[0].text, "abcdef")


if __name__ == "__main__":
    unittest.main()
