from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analyzers.disk_usage_analyzer import DiskUsageAnalyzer


class DiskUsageAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_identifies_virtualenv_node_modules_caches_and_large_files(self) -> None:
        self._write_bytes(".venv/bin/python", 128)
        self._write_text(".venv/pyvenv.cfg", "home = /usr/bin\n")
        self._write_bytes("frontend/node_modules/react/index.js", 384)
        self._write_bytes(".cache/pip/http-v2/state.bin", 64)
        self._write_bytes(".npm/_cacache/index-v5/cache.bin", 96)
        self._write_bytes("assets/big.bin", 1024)
        self._write_text("src/app.py", "print('hello')\n")

        analyzer = DiskUsageAnalyzer(
            large_file_threshold_bytes=256,
            max_hotspots=5,
            max_large_files=5,
        )
        report = analyzer.analyze(self.project_root)

        expected_total = 128 + len("home = /usr/bin\n") + 384 + 64 + 96 + 1024 + len("print('hello')\n")
        self.assertEqual(report.total_size_bytes, expected_total)

        virtualenv_paths = {Path(item.path).relative_to(self.project_root).as_posix() for item in report.virtual_environments}
        node_module_paths = {Path(item.path).relative_to(self.project_root).as_posix() for item in report.node_modules}
        cache_paths = {Path(item.path).relative_to(self.project_root).as_posix() for item in report.caches}
        large_file_paths = {Path(item.path).relative_to(self.project_root).as_posix() for item in report.large_files}

        self.assertIn(".venv", virtualenv_paths)
        self.assertIn("frontend/node_modules", node_module_paths)
        self.assertIn(".cache/pip", cache_paths)
        self.assertIn(".npm", cache_paths)
        self.assertEqual(report.category_totals["virtual_environment_bytes"], 128 + len("home = /usr/bin\n"))
        self.assertEqual(report.category_totals["node_modules_bytes"], 384)
        self.assertEqual(report.category_totals["cache_bytes"], 64 + 96)
        self.assertIn("assets/big.bin", large_file_paths)
        self.assertIn("frontend/node_modules/react/index.js", large_file_paths)
        self.assertEqual(report.largest_directories[0].size_bytes, 1024)

    def test_does_not_double_count_hard_linked_files(self) -> None:
        original = self._write_bytes("data/blob.bin", 512)
        duplicate = self.project_root / "backup" / "blob.bin"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        duplicate.hardlink_to(original)

        analyzer = DiskUsageAnalyzer(large_file_threshold_bytes=1, max_large_files=10)
        report = analyzer.analyze(self.project_root)

        self.assertEqual(report.total_size_bytes, 512)
        self.assertEqual(report.file_count, 1)
        self.assertEqual(report.duplicate_file_count, 1)
        self.assertEqual(len(report.large_files), 1)

    def test_handles_deep_and_wide_directory_trees(self) -> None:
        current = self.project_root
        for _ in range(300):
            current = current / "d"
            current.mkdir(exist_ok=True)
        self._write_bytes(current.relative_to(self.project_root).as_posix() + "/leaf.bin", 7)

        large_dir = self.project_root / "many-files"
        large_dir.mkdir()
        for index in range(1000):
            self._write_text(f"many-files/file-{index}.txt", "x")

        analyzer = DiskUsageAnalyzer(large_file_threshold_bytes=1024)
        report = analyzer.analyze(self.project_root)

        self.assertEqual(report.total_size_bytes, 1007)
        self.assertEqual(report.file_count, 1001)
        self.assertGreaterEqual(report.directory_count, 302)
        hotspot_paths = {Path(item.path).relative_to(self.project_root).as_posix() for item in report.largest_directories}
        self.assertIn("many-files", hotspot_paths)

    def _write_bytes(self, relative_path: str, size: int) -> Path:
        target = self.project_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * size)
        return target

    def _write_text(self, relative_path: str, content: str) -> Path:
        target = self.project_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


if __name__ == "__main__":
    unittest.main()
