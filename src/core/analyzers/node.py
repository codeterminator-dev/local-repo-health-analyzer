from __future__ import annotations

import json
import re
from pathlib import Path

from .base import LanguageAnalyzer
from ..models import AnalysisArtifact, DependencyEdge, DependencyNode, LanguageReport, ScanOptions


class NodeAnalyzer(LanguageAnalyzer):
    """Read-only analyzer for Node.js and TypeScript manifests/imports."""

    language = "node"
    _manifest_names = ("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")
    _source_suffixes = (".js", ".cjs", ".mjs", ".jsx", ".ts", ".tsx")
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
            for path in root_path.rglob("*")
            if path.suffix in self._source_suffixes and path.is_file() and self._is_included(path)
        )[: options.max_files_per_language]
        return AnalysisArtifact(language=self.language, manifest_paths=manifests, source_paths=source_paths)

    def analyze(self, root_path: Path, options: ScanOptions) -> LanguageReport:
        artifacts = self.discover(root_path, options)
        report = LanguageReport(language=self.language, detected=bool(artifacts.manifest_paths), artifacts=artifacts)
        if not report.detected:
            return report

        for manifest_path in artifacts.manifest_paths:
            if manifest_path.name == "package.json":
                nodes, warnings = self._parse_package_json(manifest_path)
                report.nodes.extend(nodes)
                report.warnings.extend(warnings)

        for source_path in artifacts.source_paths:
            module_node = self._source_node(root_path, source_path)
            report.nodes.append(module_node)
            try:
                content = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                report.warnings.append(f"Failed to read {source_path}: {exc}")
                continue
            report.edges.extend(self._extract_import_edges(module_node.node_id, source_path, content))

        return report

    def _parse_package_json(self, manifest_path: Path) -> tuple[list[DependencyNode], list[str]]:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ([], [f"Failed to parse {manifest_path}: {exc}"])

        nodes: list[DependencyNode] = []
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for name, version_spec in data.get(section, {}).items():
                nodes.append(
                    DependencyNode(
                        node_id=f"dep:node:{name}",
                        name=name,
                        language=self.language,
                        category=section,
                        version_spec=version_spec,
                        path=manifest_path,
                    )
                )
        return (nodes, [])

    def _source_node(self, root_path: Path, source_path: Path) -> DependencyNode:
        relative_path = source_path.relative_to(root_path)
        return DependencyNode(
            node_id=f"module:node:{relative_path.with_suffix('').as_posix()}",
            name=relative_path.as_posix(),
            language=self.language,
            category="source",
            path=source_path,
        )

    def _extract_import_edges(self, source_node_id: str, source_path: Path, content: str) -> list[DependencyEdge]:
        edges: list[DependencyEdge] = []
        patterns = (
            r'import\\s+(?:.+?\\s+from\\s+)?["\\\']([^"\\\']+)["\\\']',
            r'require\\(["\\\']([^"\\\']+)["\\\']\\)',
        )
        for pattern in patterns:
            for target in re.findall(pattern, content):
                relation = "imports-internal" if target.startswith(".") else "imports"
                target_id = (
                    f"module:node:{target}"
                    if target.startswith(".")
                    else f"dep:node:{target.split('/')[0] if not target.startswith('@') else '/'.join(target.split('/')[:2])}"
                )
                edges.append(
                    DependencyEdge(
                        source_id=source_node_id,
                        target_id=target_id,
                        relation=relation,
                        source_file=source_path,
                    )
                )
        return edges

    def _is_included(self, path: Path) -> bool:
        return not any(part in self._excluded_dirs for part in path.parts)
