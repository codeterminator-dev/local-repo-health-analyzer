from __future__ import annotations

import builtins
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from src.scanner.project_scanner import ProjectScanner


def guarded_open(file, mode="r", *args, **kwargs):
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        raise AssertionError(f"Write-capable open detected for {file}: {mode}")
    return ORIGINAL_OPEN(file, mode, *args, **kwargs)


def fail_write_api(*args, **kwargs):
    raise AssertionError(f"Unexpected write API usage: args={args}, kwargs={kwargs}")


ORIGINAL_OPEN = builtins.open


class ProjectScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scan_discovers_nested_python_and_node_projects(self) -> None:
        self._touch("workspace/apps/api/requirements.txt")
        self._touch("workspace/apps/web/package.json")
        self._touch("workspace/libs/shared/README.md")
        self._touch("workspace/services/hybrid/package.json")
        self._touch("workspace/services/hybrid/pyproject.toml")

        scanner = ProjectScanner(str(self.root / "workspace"))

        projects = scanner.scan()
        by_name = {project.name: project for project in projects}

        self.assertEqual({"api", "hybrid", "web"}, set(by_name))
        self.assertEqual(("python",), by_name["api"].project_types)
        self.assertEqual(("node",), by_name["web"].project_types)
        self.assertEqual(("python", "node"), by_name["hybrid"].project_types)
        self.assertEqual(
            (
                str((self.root / "workspace/apps/api").resolve()),
                str((self.root / "workspace/apps/web").resolve()),
                str((self.root / "workspace/services/hybrid").resolve()),
            ),
            tuple(project.path for project in projects),
        )

    def test_scan_skips_symlinked_directories_and_out_of_root_targets(self) -> None:
        self._touch("workspace/projects/backend/requirements.txt")
        os.symlink(self.root / "workspace/projects/backend", self.root / "workspace/backend-link")

        external_dir = self.root / "external-node"
        external_dir.mkdir()
        (external_dir / "package.json").write_text("{}", encoding="utf-8")
        os.symlink(external_dir, self.root / "workspace/external-link")

        scanner = ProjectScanner(str(self.root / "workspace"))

        projects = scanner.scan()

        self.assertEqual(1, len(projects))
        self.assertEqual("backend", projects[0].name)
        self.assertEqual(("python",), projects[0].project_types)

    def test_scan_can_follow_safe_symlink_directories_without_duplicates(self) -> None:
        self._touch("workspace/projects/backend/requirements.txt")
        os.symlink(self.root / "workspace/projects/backend", self.root / "workspace/backend-link")

        scanner = ProjectScanner(str(self.root / "workspace"), follow_symlink_dirs=True)

        projects = scanner.scan()

        self.assertEqual(1, len(projects))
        self.assertEqual(str((self.root / "workspace/projects/backend").resolve()), projects[0].path)

    def test_rejects_root_paths_outside_existing_directory(self) -> None:
        with self.assertRaises(ValueError):
            ProjectScanner(str(self.root / "../does-not-exist"))

    def test_scan_uses_only_read_only_operations(self) -> None:
        self._touch("workspace/app/package.json")
        scanner = ProjectScanner(str(self.root / "workspace"))

        with mock.patch("builtins.open", side_effect=guarded_open), mock.patch("os.mkdir", side_effect=fail_write_api), mock.patch(
            "os.makedirs", side_effect=fail_write_api
        ), mock.patch("os.remove", side_effect=fail_write_api), mock.patch(
            "os.unlink", side_effect=fail_write_api
        ), mock.patch(
            "os.replace", side_effect=fail_write_api
        ), mock.patch(
            "os.rename", side_effect=fail_write_api
        ), mock.patch(
            "os.rmdir", side_effect=fail_write_api
        ), mock.patch(
            "pathlib.Path.write_text", side_effect=fail_write_api
        ), mock.patch(
            "pathlib.Path.write_bytes", side_effect=fail_write_api
        ), mock.patch(
            "pathlib.Path.mkdir", side_effect=fail_write_api
        ), mock.patch(
            "pathlib.Path.touch", side_effect=fail_write_api
        ), mock.patch(
            "pathlib.Path.unlink", side_effect=fail_write_api
        ), mock.patch(
            "shutil.rmtree", side_effect=fail_write_api
        ):
            projects = scanner.scan()

        self.assertEqual(1, len(projects))
        self.assertEqual("app", projects[0].name)

    def _touch(self, relative_path: str, content: str = "") -> None:
        file_path = self.root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
