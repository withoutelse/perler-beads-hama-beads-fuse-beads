import tempfile
import unittest
from pathlib import Path

from app.pipeline.adapters.storage import LocalArtifactStorage


class LocalArtifactStorageTests(unittest.TestCase):
    def test_saves_original_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalArtifactStorage(Path(tmp))
            path = storage.save_original_image(
                "prj_test",
                image_id="img_001",
                filename="front.jpg",
                data=b"image-bytes",
            )
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"image-bytes")
            self.assertIn("projects", path.parts)
            self.assertIn("prj_test", path.parts)

    def test_project_root_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalArtifactStorage(Path(tmp))
            with self.assertRaises(ValueError):
                storage.project_root("../escape")

    def test_path_for_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalArtifactStorage(Path(tmp))
            with self.assertRaises(ValueError):
                storage.path_for("../escape.txt")

    def test_model_and_artifact_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalArtifactStorage(Path(tmp))
            self.assertTrue(storage.model_dir("prj_test").is_dir())
            self.assertTrue(storage.artifact_dir("prj_test").is_dir())


if __name__ == "__main__":
    unittest.main()
