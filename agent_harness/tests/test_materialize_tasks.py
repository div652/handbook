import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_tasks import materialize_tasks


class MaterializeTasksTests(unittest.TestCase):
    def create_repository(self, root: Path, parent: str = "handbook_base") -> Path:
        source = root / "tasks"
        for task_name in ("task_a", "task_b"):
            task = source / task_name
            environment = task / "environment"
            environment.mkdir(parents=True)
            (task / "task.toml").write_text("[metadata]\n")
            (environment / "Dockerfile").write_text(
                f"FROM {parent}\nRUN true\n"
            )
        (source / "task_a" / "ignored.pyc").write_bytes(b"ignored")
        (root / ".gitignore").write_text("*.pyc\n")
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "test",
            ],
            check=True,
        )
        return source

    def test_copies_tasks_with_pinned_base_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self.create_repository(root)
            destination = root / "snapshot"

            materialize_tasks(
                root,
                source,
                destination,
                "handbook_base:sha256-content",
                expected_count=2,
            )

            for dockerfile in destination.glob("*/environment/Dockerfile"):
                self.assertEqual(
                    dockerfile.read_text().splitlines()[0],
                    "FROM handbook_base:sha256-content",
                )
            self.assertEqual(
                (source / "task_a" / "environment" / "Dockerfile")
                .read_text()
                .splitlines()[0],
                "FROM handbook_base",
            )
            self.assertFalse((destination / "task_a" / "ignored.pyc").exists())

    def test_refuses_unexpected_source_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self.create_repository(root, parent="another_base")

            with self.assertRaisesRegex(ValueError, "must start"):
                materialize_tasks(
                    root,
                    source,
                    root / "snapshot",
                    "handbook_base:sha256-content",
                    expected_count=2,
                )
            self.assertFalse((root / "snapshot").exists())


if __name__ == "__main__":
    unittest.main()
