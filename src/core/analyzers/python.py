from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from .base import LanguageAnalyzer
from ..models import AnalysisArtifact, DependencyEdge, DependencyNode, LanguageReport, ScanOptions


class PythonAnalyzer(LanguageAnalyzer):
    """Read-only analyzer for Python manifests and import relationships."""

    language = "python"
    _manifest_names = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile")
    _excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}

    def detect(self, root_path: Path) -> bool:
        return any(
            self._is_included(path)
            for name in self._manifest_names
            for path in root_path.rglob(name)
        )

    def discover(self, root_path: Path, options: ScanOptions) -> AnalysisArtifact:
        manifests = tuple(
            path
            for name in self._manifest_names
            for path in root_path.rglob(name)
            if self._is_included(path)
        )
        source_paths = tuple(
            path
            for path in root_path.rglob("*.py")
            if self._is_included(path)
        )[: options.max_files_per_language]
        return AnalysisArtifact(language=self.language, manifest_paths=manifests, source_paths=source_paths)

    def analyze(self, root_path: Path, options: ScanOptions) -> LanguageReport:
        artifacts = self.discover(root_path, options)
        report = LanguageReport(language=self.language, detected=bool(artifacts.manifest_paths), artifacts=artifacts)
        if not report.detected:
            return report

        for manifest_path in artifacts.manifest_paths:
            if manifest_path.name == "pyproject.toml":
                report.nodes.extend(self._parse_pyproject(manifest_path))
            elif manifest_path.name == "requirements.txt":
                report.nodes.extend(self._parse_requirements(manifest_path))

        for source_path in artifacts.source_paths:
            module_node = self._source_node(root_path, source_path)
            report.nodes.append(module_node)
            try:
                tree = ast.parse(source_path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                report.warnings.append(f"Failed to parse {source_path}: {exc}")
                continue
            report.edges.extend(self._extract_import_edges(module_node.node_id, source_path, tree))

        return report

    def _parse_pyproject(self, manifest_path: Path) -> list[DependencyNode]:
        try:
            data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return [self._warning_node(manifest_path, f"pyproject-parse-error:{exc}")]

        dependencies: list[DependencyNode] = []
        project = data.get("project", {})
        for entry in project.get("dependencies", []):
            dependencies.append(self._external_dependency(entry, manifest_path, "runtime"))
        for group, entries in data.get("project", {}).get("optional-dependencies", {}).items():
            for entry in entries:
                dependencies.append(self._external_dependency(entry, manifest_path, f"optional:{group}"))
        return dependencies

    def _parse_requirements(self, manifest_path: Path) -> list[DependencyNode]:
        nodes: list[DependencyNode] = []
        try:
            content = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [self._warning_node(manifest_path, f"requirements-read-error:{exc}")]

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            nodes.append(self._external_dependency(line, manifest_path, "runtime"))
        return nodes

    def _external_dependency(self, spec: str, manifest_path: Path, category: str) -> DependencyNode:
        name = re.split(r"[<>=!~\\[]", spec, maxsplit=1)[0].strip()
        return DependencyNode(
            node_id=f"dep:python:{name}",
            name=name,
            language=self.language,
            category=category,
            version_spec=spec,
            path=manifest_path,
        )

    def _source_node(self, root_path: Path, source_path: Path) -> DependencyNode:
        relative_path = source_path.relative_to(root_path)
        module_name = ".".join(relative_path.with_suffix("").parts)
        return DependencyNode(
            node_id=f"module:python:{module_name}",
            name=module_name,
            language=self.language,
            category="source",
            path=source_path,
        )

    def _extract_import_edges(self, source_node_id: str, source_path: Path, tree: ast.AST) -> list[DependencyEdge]:
        edges: list[DependencyEdge] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(
                        DependencyEdge(
                            source_id=source_node_id,
                            target_id=f"dep:python:{alias.name.split('.')[0]}",
                            relation="imports",
                            source_file=source_path,
                        )
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                edges.append(
                    DependencyEdge(
                        source_id=source_node_id,
                        target_id=f"dep:python:{node.module.split('.')[0]}",
                        relation="imports",
                        source_file=source_path,
                    )
                )
        return edges

    def _warning_node(self, manifest_path: Path, message: str) -> DependencyNode:
        return DependencyNode(
            node_id=f"warning:python:{manifest_path.name}:{message}",
            name=manifest_path.name,
            language=self.language,
            category="warning",
            path=manifest_path,
            metadata={"warning": message},
        )

    def _is_included(self, path: Path) -> bool:
        return not any(part in self._excluded_dirs for part in path.parts)
