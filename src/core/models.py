from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class DependencyNode:
    """A dependency or source module discovered during read-only analysis."""

    node_id: str
    name: str
    language: str
    category: str
    version_spec: str | None = None
    path: Path | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DependencyEdge:
    """A directed relationship between two dependency graph nodes."""

    source_id: str
    target_id: str
    relation: str
    source_file: Path | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class DependencyGraph:
    """An aggregated graph merged from all language-specific analyzers."""

    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)

    def add_node(self, node: DependencyNode) -> None:
        self.nodes.setdefault(node.node_id, node)

    def add_edge(self, edge: DependencyEdge) -> None:
        if edge not in self.edges:
            self.edges.append(edge)


@dataclass(slots=True, frozen=True)
class AnalysisArtifact:
    """A language-specific set of files eligible for analysis."""

    language: str
    manifest_paths: tuple[Path, ...]
    source_paths: tuple[Path, ...]


@dataclass(slots=True)
class LanguageReport:
    """The output from a single language analyzer."""

    language: str
    detected: bool
    artifacts: AnalysisArtifact
    nodes: list[DependencyNode] = field(default_factory=list)
    edges: list[DependencyEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ScanOptions:
    """Read-only scan configuration."""

    include_languages: tuple[str, ...] = ()
    respect_gitignore: bool = True
    max_files_per_language: int = 5000


@dataclass(slots=True)
class ScanReport:
    """Top-level result returned by the scanner orchestration layer."""

    root_path: Path
    reports: list[LanguageReport]
    dependency_graph: DependencyGraph
    warnings: list[str] = field(default_factory=list)
