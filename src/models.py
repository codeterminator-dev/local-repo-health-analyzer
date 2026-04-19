from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


def normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def merge_specifiers(current: str, incoming: str) -> str:
    if not incoming:
        return current
    if not current:
        return incoming
    if incoming == current:
        return current

    seen: list[str] = []
    for part in [*current.split(","), *incoming.split(",")]:
        value = part.strip()
        if value and value not in seen:
            seen.append(value)
    return ",".join(seen)


@dataclass(slots=True)
class DependencySpec:
    name: str
    version_spec: str = ""
    dependency_type: str = "package"
    path: str | None = None
    editable: bool = False
    marker: str | None = None
    groups: tuple[str, ...] = ()
    manifest_path: str | None = None
    raw: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize_name(self.name)


@dataclass(slots=True)
class ManifestParseResult:
    project_name: str | None = None
    dependencies: list[DependencySpec] = field(default_factory=list)


@dataclass(slots=True)
class DependencyNode:
    name: str
    version_spec: str = ""
    dependency_type: str = "package"
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize_name(self.name)


@dataclass(slots=True)
class DependencyEdge:
    source: str
    target: str
    manifests: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class DependencyGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, DependencyNode] = {}
        self.edges: dict[tuple[str, str], DependencyEdge] = {}

    def add_node(
        self,
        name: str,
        *,
        version_spec: str = "",
        dependency_type: str = "package",
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DependencyNode:
        key = normalize_name(name)
        node = self.nodes.get(key)
        if node is None:
            node = DependencyNode(
                name=name,
                version_spec=version_spec,
                dependency_type=dependency_type,
                path=path,
                metadata=dict(metadata or {}),
            )
            self.nodes[key] = node
            return node

        if version_spec:
            node.version_spec = merge_specifiers(node.version_spec, version_spec)
        if path and not node.path:
            node.path = path
        if dependency_type == "project" or node.dependency_type != "project":
            node.dependency_type = dependency_type
        if metadata:
            node.metadata.update(metadata)
        return node

    def add_dependency(self, source: str, dependency: DependencySpec) -> DependencyEdge:
        self.add_node(
            dependency.name,
            version_spec=dependency.version_spec,
            dependency_type=dependency.dependency_type,
            path=dependency.path,
            metadata={
                **dependency.metadata,
                **({"marker": dependency.marker} if dependency.marker else {}),
            },
        )
        return self.add_edge(
            source,
            dependency.name,
            manifest_path=dependency.manifest_path,
            groups=dependency.groups,
            metadata={
                "editable": dependency.editable,
                **({"raw": dependency.raw} if dependency.raw else {}),
            },
        )

    def add_edge(
        self,
        source: str,
        target: str,
        *,
        manifest_path: str | None = None,
        groups: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> DependencyEdge:
        source_node = self.add_node(source)
        target_node = self.add_node(target)
        edge_key = (source_node.key, target_node.key)
        manifests = tuple(sorted({manifest_path} - {None}))
        edge = self.edges.get(edge_key)
        if edge is None:
            edge = DependencyEdge(
                source=source_node.name,
                target=target_node.name,
                manifests=manifests,
                groups=tuple(sorted(set(groups))),
                metadata=dict(metadata or {}),
            )
            self.edges[edge_key] = edge
            return edge

        edge.manifests = tuple(sorted(set(edge.manifests).union(manifests)))
        edge.groups = tuple(sorted(set(edge.groups).union(groups)))
        if metadata:
            edge.metadata.update(metadata)
        return edge

    def has_node(self, name: str) -> bool:
        return normalize_name(name) in self.nodes

    def has_edge(self, source: str, target: str) -> bool:
        return (normalize_name(source), normalize_name(target)) in self.edges

    def direct_dependencies_of(self, source: str) -> set[str]:
        source_key = normalize_name(source)
        return {
            edge.target
            for (edge_source, _), edge in self.edges.items()
            if edge_source == source_key
        }

    def dependencies_of(self, source: str, *, transitive: bool = False) -> set[str]:
        direct = self.direct_dependencies_of(source)
        if not transitive:
            return direct

        source_key = normalize_name(source)
        visited: set[str] = set()
        queue = deque(direct)
        while queue:
            current = queue.popleft()
            current_key = normalize_name(current)
            if current_key in visited or current_key == source_key:
                continue
            visited.add(current_key)
            for child in self.direct_dependencies_of(current):
                if normalize_name(child) not in visited:
                    queue.append(child)
        return {self.nodes[key].name for key in visited}

    def indirect_dependencies_of(self, source: str) -> set[str]:
        transitive = self.dependencies_of(source, transitive=True)
        return transitive.difference(self.direct_dependencies_of(source))

