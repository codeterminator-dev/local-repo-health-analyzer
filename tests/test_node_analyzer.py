from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analyzers.node_analyzer import ROOT_NODE, NodeAnalyzer


class NodeAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = NodeAnalyzer()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_prefers_package_lock_and_builds_npm_topology(self) -> None:
        self._write_json(
            "package.json",
            {
                "name": "npm-project",
                "dependencies": {"prod-a": "^1.0.0"},
                "devDependencies": {"dev-b": "^2.0.0"},
            },
        )
        self._write_json(
            "package-lock.json",
            {
                "name": "npm-project",
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "name": "npm-project",
                        "dependencies": {"prod-a": "^1.0.0"},
                        "devDependencies": {"dev-b": "^2.0.0"},
                    },
                    "node_modules/prod-a": {
                        "version": "1.0.1",
                        "dependencies": {"shared-c": "^3.0.0"},
                    },
                    "node_modules/dev-b": {
                        "version": "2.1.0",
                        "dev": True,
                        "dependencies": {"shared-c": "^3.0.0"},
                    },
                    "node_modules/shared-c": {
                        "version": "3.2.1",
                    },
                },
            },
        )

        result = self.analyzer.analyze(self.project_root)

        self.assertEqual(result.package_manager, "npm")
        self.assertEqual(result.source_file, "package-lock.json")
        self.assertEqual(
            result.topology[ROOT_NODE],
            ["node_modules/dev-b", "node_modules/prod-a"],
        )
        self.assertEqual(
            result.topology["node_modules/prod-a"],
            ["node_modules/shared-c"],
        )
        self.assertEqual(
            result.topology["node_modules/dev-b"],
            ["node_modules/shared-c"],
        )
        self.assertEqual(
            result.dependency_nodes["node_modules/prod-a"].dependency_type,
            "production",
        )
        self.assertEqual(
            result.dependency_nodes["node_modules/dev-b"].dependency_type,
            "development",
        )
        self.assertEqual(
            result.dependency_nodes["node_modules/shared-c"].dependency_type,
            "production",
        )

    def test_parses_yarn_lock_and_marks_transitive_dev_dependencies(self) -> None:
        self._write_json(
            "package.json",
            {
                "name": "yarn-project",
                "dependencies": {"react": "^18.2.0"},
                "devDependencies": {"vite": "^5.0.0"},
            },
        )
        self.project_root.joinpath("yarn.lock").write_text(
            '\n'.join(
                [
                    'react@^18.2.0:',
                    '  version "18.2.0"',
                    "",
                    'vite@^5.0.0:',
                    '  version "5.1.0"',
                    "  dependencies:",
                    '    esbuild "^0.20.0"',
                    "",
                    'esbuild@^0.20.0:',
                    '  version "0.20.2"',
                ]
            ),
            encoding="utf-8",
        )

        result = self.analyzer.analyze(self.project_root)

        self.assertEqual(result.package_manager, "yarn")
        self.assertEqual(result.source_file, "yarn.lock")
        self.assertEqual(result.topology[ROOT_NODE], ["react@18.2.0", "vite@5.1.0"])
        self.assertEqual(result.topology["vite@5.1.0"], ["esbuild@0.20.2"])
        self.assertEqual(result.dependency_nodes["vite@5.1.0"].dependency_type, "development")
        self.assertEqual(
            result.dependency_nodes["esbuild@0.20.2"].dependency_type,
            "development",
        )

    def test_falls_back_to_node_modules_when_no_lockfile_exists(self) -> None:
        self._write_json(
            "package.json",
            {
                "name": "node-modules-project",
                "dependencies": {"express": "^1.0.0"},
            },
        )
        self._write_json(
            "node_modules/express/package.json",
            {
                "name": "express",
                "version": "1.0.0",
                "dependencies": {"qs": "^2.0.0"},
            },
        )
        self._write_json(
            "node_modules/qs/package.json",
            {
                "name": "qs",
                "version": "2.1.0",
            },
        )

        result = self.analyzer.analyze(self.project_root)

        self.assertEqual(result.package_manager, "node_modules")
        self.assertEqual(result.topology[ROOT_NODE], ["node_modules/express"])
        self.assertEqual(result.topology["node_modules/express"], ["node_modules/qs"])
        self.assertEqual(
            result.dependency_nodes["node_modules/qs"].dependency_type,
            "production",
        )

    def test_uses_legacy_package_lock_v1_structure(self) -> None:
        self._write_json(
            "package.json",
            {
                "name": "legacy-npm-project",
                "dependencies": {"left-pad": "^1.0.0"},
                "devDependencies": {"jest": "^29.0.0"},
            },
        )
        self._write_json(
            "package-lock.json",
            {
                "name": "legacy-npm-project",
                "lockfileVersion": 1,
                "dependencies": {
                    "left-pad": {
                        "version": "1.3.0",
                    },
                    "jest": {
                        "version": "29.7.0",
                        "dev": True,
                        "dependencies": {
                            "chalk": {
                                "version": "5.4.1",
                            }
                        },
                    },
                },
            },
        )

        result = self.analyzer.analyze(self.project_root)

        self.assertEqual(result.package_manager, "npm")
        self.assertEqual(result.topology[ROOT_NODE], ["node_modules/jest", "node_modules/left-pad"])
        self.assertEqual(result.topology["node_modules/jest"], ["node_modules/jest/node_modules/chalk"])
        self.assertEqual(
            result.dependency_nodes["node_modules/jest/node_modules/chalk"].dependency_type,
            "development",
        )

    def _write_json(self, relative_path: str, payload: dict) -> None:
        target_path = self.project_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
