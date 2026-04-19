from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT_NODE = "__root__"
DEPENDENCY_FIELDS = {
    "dependencies": "production",
    "devDependencies": "development",
    "optionalDependencies": "optional",
    "peerDependencies": "peer",
}
DEPENDENCY_TYPE_RANK = {
    "unknown": 0,
    "development": 1,
    "peer": 2,
    "optional": 3,
    "production": 4,
}


@dataclass
class DependencyNode:
    key: str
    name: str
    version: str | None
    declared_version: str | None
    dependency_type: str
    source: str
    dependencies: list[str] = field(default_factory=list)
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NodeAnalysis:
    package_name: str
    package_manager: str
    source_file: str | None
    root_dependencies: dict[str, str]
    dependency_nodes: dict[str, DependencyNode]
    topology: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "package_manager": self.package_manager,
            "source_file": self.source_file,
            "root_dependencies": dict(self.root_dependencies),
            "dependency_nodes": {
                key: node.to_dict() for key, node in self.dependency_nodes.items()
            },
            "topology": {key: list(children) for key, children in self.topology.items()},
        }


class NodeAnalyzer:
    """Analyze Node.js dependency metadata and build a dependency topology."""

    def analyze(self, project_path: str | Path) -> NodeAnalysis:
        root = Path(project_path)
        package_json_path = root / "package.json"
        if not package_json_path.exists():
            raise FileNotFoundError(f"package.json not found under {root}")

        package_json = self._load_json(package_json_path)
        root_types, root_specs = self._collect_root_dependencies(package_json)

        package_lock_path = root / "package-lock.json"
        if package_lock_path.exists():
            return self._analyze_package_lock(
                root=root,
                package_json=package_json,
                root_types=root_types,
                root_specs=root_specs,
                package_lock_path=package_lock_path,
            )

        yarn_lock_path = root / "yarn.lock"
        if yarn_lock_path.exists():
            return self._analyze_yarn_lock(
                root=root,
                package_json=package_json,
                root_types=root_types,
                root_specs=root_specs,
                yarn_lock_path=yarn_lock_path,
            )

        node_modules_path = root / "node_modules"
        if node_modules_path.exists():
            return self._analyze_node_modules(
                root=root,
                package_json=package_json,
                root_types=root_types,
                root_specs=root_specs,
                node_modules_path=node_modules_path,
            )

        return self._build_package_json_only_analysis(
            package_json=package_json,
            root_types=root_types,
            root_specs=root_specs,
        )

    def _analyze_package_lock(
        self,
        *,
        root: Path,
        package_json: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
        package_lock_path: Path,
    ) -> NodeAnalysis:
        package_lock = self._load_json(package_lock_path)
        if isinstance(package_lock.get("packages"), dict):
            nodes, topology = self._parse_package_lock_packages(
                package_lock=package_lock,
                root_types=root_types,
                root_specs=root_specs,
            )
        else:
            nodes, topology = self._parse_package_lock_v1(
                package_lock=package_lock,
                root_types=root_types,
                root_specs=root_specs,
            )

        self._propagate_dependency_types(nodes=nodes, topology=topology)
        return NodeAnalysis(
            package_name=package_json.get("name", root.name),
            package_manager="npm",
            source_file=str(package_lock_path.relative_to(root)),
            root_dependencies=root_types,
            dependency_nodes=nodes,
            topology=topology,
        )

    def _parse_package_lock_packages(
        self,
        *,
        package_lock: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
    ) -> tuple[dict[str, DependencyNode], dict[str, list[str]]]:
        packages: dict[str, dict[str, Any]] = package_lock["packages"]
        nodes: dict[str, DependencyNode] = {}
        topology: dict[str, list[str]] = {ROOT_NODE: []}

        for package_path, payload in packages.items():
            if package_path == "":
                continue
            name = payload.get("name") or self._package_name_from_path(package_path)
            dependency_type = root_types.get(name)
            if dependency_type is None:
                if payload.get("optional"):
                    dependency_type = "optional"
                elif payload.get("dev"):
                    dependency_type = "development"
                else:
                    dependency_type = "unknown"

            child_keys = []
            for dependency_name in payload.get("dependencies", {}):
                child_key = self._resolve_path_dependency(package_path, dependency_name, packages)
                if child_key:
                    child_keys.append(child_key)

            nodes[package_path] = DependencyNode(
                key=package_path,
                name=name,
                version=payload.get("version"),
                declared_version=root_specs.get(name),
                dependency_type=dependency_type,
                source="package-lock",
                dependencies=self._sorted_unique(child_keys),
                path=package_path,
            )
            topology[package_path] = self._sorted_unique(child_keys)

        root_entry = packages.get("", {})
        root_dependency_names = self._ordered_root_dependency_names(root_types, root_entry)
        topology[ROOT_NODE] = self._sorted_unique(
            [
                child_key
                for dependency_name in root_dependency_names
                if (child_key := self._resolve_path_dependency("", dependency_name, packages))
            ]
        )
        return nodes, topology

    def _parse_package_lock_v1(
        self,
        *,
        package_lock: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
    ) -> tuple[dict[str, DependencyNode], dict[str, list[str]]]:
        flattened: dict[str, dict[str, Any]] = {}
        dependency_tree = package_lock.get("dependencies", {})

        def walk_dependencies(
            current_dependencies: dict[str, Any],
            parent_path: str,
            inherited_type: str,
        ) -> None:
            for dependency_name, payload in current_dependencies.items():
                current_path = (
                    f"{parent_path}/node_modules/{dependency_name}"
                    if parent_path
                    else f"node_modules/{dependency_name}"
                )
                dependency_type = root_types.get(dependency_name)
                if dependency_type is None:
                    if payload.get("optional"):
                        dependency_type = "optional"
                    elif payload.get("dev"):
                        dependency_type = "development"
                    else:
                        dependency_type = inherited_type

                flattened[current_path] = {
                    "name": dependency_name,
                    "version": payload.get("version"),
                    "declared_version": root_specs.get(dependency_name),
                    "dependency_type": dependency_type,
                    "required_names": self._sorted_unique(
                        list(payload.get("requires", {}).keys())
                        + list(payload.get("dependencies", {}).keys())
                    ),
                }
                walk_dependencies(
                    payload.get("dependencies", {}),
                    current_path,
                    dependency_type,
                )

        for dependency_name, payload in dependency_tree.items():
            inherited_type = root_types.get(dependency_name, "production")
            walk_dependencies({dependency_name: payload}, "", inherited_type)

        installed_paths = set(flattened)
        nodes: dict[str, DependencyNode] = {}
        topology: dict[str, list[str]] = {ROOT_NODE: []}

        for package_path, payload in flattened.items():
            child_keys = [
                child_key
                for dependency_name in payload["required_names"]
                if (child_key := self._resolve_path_dependency(package_path, dependency_name, installed_paths))
            ]
            nodes[package_path] = DependencyNode(
                key=package_path,
                name=payload["name"],
                version=payload["version"],
                declared_version=payload["declared_version"],
                dependency_type=payload["dependency_type"],
                source="package-lock",
                dependencies=self._sorted_unique(child_keys),
                path=package_path,
            )
            topology[package_path] = self._sorted_unique(child_keys)

        topology[ROOT_NODE] = self._sorted_unique(
            [
                child_key
                for dependency_name in root_types
                if (child_key := self._resolve_path_dependency("", dependency_name, installed_paths))
            ]
        )
        return nodes, topology

    def _analyze_yarn_lock(
        self,
        *,
        root: Path,
        package_json: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
        yarn_lock_path: Path,
    ) -> NodeAnalysis:
        lock_entries = self._parse_yarn_lock(yarn_lock_path.read_text(encoding="utf-8"))
        selector_index: dict[str, dict[str, Any]] = {}
        for entry in lock_entries:
            for selector in entry["selectors"]:
                selector_index[selector] = entry

        nodes: dict[str, DependencyNode] = {}
        topology: dict[str, list[str]] = {ROOT_NODE: []}
        selector_to_node: dict[str, str] = {}

        def ensure_entry(selector: str, dependency_type: str | None = None) -> str | None:
            entry = selector_index.get(selector)
            if entry is None:
                return None

            node_key = selector_to_node.get(selector)
            if node_key is None:
                node_key = f"{entry['name']}@{entry['version']}"
                selector_to_node[selector] = node_key
            if node_key not in nodes:
                nodes[node_key] = DependencyNode(
                    key=node_key,
                    name=entry["name"],
                    version=entry["version"],
                    declared_version=root_specs.get(entry["name"]),
                    dependency_type=dependency_type or root_types.get(entry["name"], "unknown"),
                    source="yarn.lock",
                    dependencies=[],
                    path=node_key,
                )

                child_keys = []
                inherited_type = nodes[node_key].dependency_type
                for child_name, requested_selector in entry["dependencies"].items():
                    resolved_selector = self._resolve_yarn_selector(
                        name=child_name,
                        requested_selector=requested_selector,
                        selector_index=selector_index,
                    )
                    if resolved_selector is None:
                        continue
                    child_key = ensure_entry(resolved_selector, inherited_type)
                    if child_key:
                        child_keys.append(child_key)
                nodes[node_key].dependencies = self._sorted_unique(child_keys)
                topology[node_key] = self._sorted_unique(child_keys)
            elif dependency_type and nodes[node_key].dependency_type == "unknown":
                nodes[node_key].dependency_type = dependency_type

            return node_key

        root_edges = []
        for dependency_name in self._ordered_root_dependency_names(root_types, package_json):
            requested_selector = root_specs.get(dependency_name)
            if requested_selector is None:
                continue
            selector = self._resolve_yarn_selector(
                name=dependency_name,
                requested_selector=requested_selector,
                selector_index=selector_index,
            )
            if selector is None:
                continue
            node_key = ensure_entry(selector, root_types[dependency_name])
            if node_key:
                root_edges.append(node_key)

        topology[ROOT_NODE] = self._sorted_unique(root_edges)
        self._propagate_dependency_types(nodes=nodes, topology=topology)
        return NodeAnalysis(
            package_name=package_json.get("name", root.name),
            package_manager="yarn",
            source_file=str(yarn_lock_path.relative_to(root)),
            root_dependencies=root_types,
            dependency_nodes=nodes,
            topology=topology,
        )

    def _analyze_node_modules(
        self,
        *,
        root: Path,
        package_json: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
        node_modules_path: Path,
    ) -> NodeAnalysis:
        installed_packages: dict[str, dict[str, Any]] = {}
        for package_json_path in node_modules_path.glob("**/package.json"):
            relative_path = str(package_json_path.relative_to(root))
            package_data = self._load_json(package_json_path)
            name = package_data.get("name") or self._package_name_from_path(relative_path.removesuffix("/package.json"))
            installed_packages[relative_path.removesuffix("/package.json")] = {
                "name": name,
                "version": package_data.get("version"),
                "dependencies": package_data.get("dependencies", {}),
            }

        nodes: dict[str, DependencyNode] = {}
        topology: dict[str, list[str]] = {ROOT_NODE: []}
        installed_paths = set(installed_packages)

        for package_path, payload in installed_packages.items():
            child_keys = [
                child_key
                for dependency_name in payload["dependencies"]
                if (child_key := self._resolve_path_dependency(package_path, dependency_name, installed_paths))
            ]
            nodes[package_path] = DependencyNode(
                key=package_path,
                name=payload["name"],
                version=payload["version"],
                declared_version=root_specs.get(payload["name"]),
                dependency_type=root_types.get(payload["name"], "unknown"),
                source="node_modules",
                dependencies=self._sorted_unique(child_keys),
                path=package_path,
            )
            topology[package_path] = self._sorted_unique(child_keys)

        topology[ROOT_NODE] = self._sorted_unique(
            [
                child_key
                for dependency_name in root_types
                if (child_key := self._resolve_path_dependency("", dependency_name, installed_paths))
            ]
        )
        self._propagate_dependency_types(nodes=nodes, topology=topology)
        return NodeAnalysis(
            package_name=package_json.get("name", root.name),
            package_manager="node_modules",
            source_file="node_modules",
            root_dependencies=root_types,
            dependency_nodes=nodes,
            topology=topology,
        )

    def _build_package_json_only_analysis(
        self,
        *,
        package_json: dict[str, Any],
        root_types: dict[str, str],
        root_specs: dict[str, str],
    ) -> NodeAnalysis:
        nodes = {}
        topology = {ROOT_NODE: []}
        for dependency_name, dependency_type in root_types.items():
            package_path = f"node_modules/{dependency_name}"
            nodes[package_path] = DependencyNode(
                key=package_path,
                name=dependency_name,
                version=None,
                declared_version=root_specs.get(dependency_name),
                dependency_type=dependency_type,
                source="package.json",
                dependencies=[],
                path=package_path,
            )
            topology[ROOT_NODE].append(package_path)
            topology[package_path] = []

        topology[ROOT_NODE] = self._sorted_unique(topology[ROOT_NODE])
        return NodeAnalysis(
            package_name=package_json.get("name", "unknown"),
            package_manager="package.json",
            source_file="package.json",
            root_dependencies=root_types,
            dependency_nodes=nodes,
            topology=topology,
        )

    def _collect_root_dependencies(
        self, package_json: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, str]]:
        dependency_types: dict[str, str] = {}
        dependency_specs: dict[str, str] = {}
        for field_name, dependency_type in DEPENDENCY_FIELDS.items():
            dependencies = package_json.get(field_name, {})
            if not isinstance(dependencies, dict):
                continue
            for name, version_spec in dependencies.items():
                dependency_types.setdefault(name, dependency_type)
                dependency_specs[name] = version_spec
        return dependency_types, dependency_specs

    def _propagate_dependency_types(
        self,
        *,
        nodes: dict[str, DependencyNode],
        topology: dict[str, list[str]],
    ) -> None:
        queue: deque[tuple[str, str]] = deque()
        assigned_types: dict[str, str] = {}

        for root_child in topology.get(ROOT_NODE, []):
            node = nodes.get(root_child)
            if node is None:
                continue
            queue.append((root_child, node.dependency_type))
            assigned_types[root_child] = node.dependency_type

        while queue:
            current_key, inherited_type = queue.popleft()
            current_node = nodes.get(current_key)
            if current_node is None:
                continue

            current_type = self._merge_dependency_type(
                current_node.dependency_type,
                inherited_type,
            )
            current_node.dependency_type = current_type

            child_type = current_type
            for child_key in topology.get(current_key, []):
                child_node = nodes.get(child_key)
                if child_node is None:
                    continue
                existing = assigned_types.get(child_key)
                next_type = self._merge_dependency_type(existing or "unknown", child_type)
                if existing is None:
                    assigned_types[child_key] = next_type
                    queue.append((child_key, child_type))
                elif next_type != existing:
                    assigned_types[child_key] = next_type
                    queue.append((child_key, next_type))

    def _ordered_root_dependency_names(
        self,
        root_types: dict[str, str],
        source: dict[str, Any],
    ) -> list[str]:
        ordered_names: list[str] = []
        for field_name in DEPENDENCY_FIELDS:
            dependencies = source.get(field_name, {})
            if isinstance(dependencies, dict):
                ordered_names.extend(dependencies.keys())

        if ordered_names:
            return self._sorted_unique(ordered_names)
        return self._sorted_unique(list(root_types.keys()))

    def _resolve_path_dependency(
        self,
        current_path: str,
        dependency_name: str,
        installed_entries: dict[str, Any] | set[str],
    ) -> str | None:
        installed_paths = (
            set(installed_entries.keys())
            if isinstance(installed_entries, dict)
            else set(installed_entries)
        )
        for ancestor_path in self._iter_path_ancestors(current_path):
            if ancestor_path:
                candidate = f"{ancestor_path}/node_modules/{dependency_name}"
            else:
                candidate = f"node_modules/{dependency_name}"
            if candidate in installed_paths:
                return candidate

        matching = [
            path
            for path in installed_paths
            if path == f"node_modules/{dependency_name}"
            or path.endswith(f"/node_modules/{dependency_name}")
        ]
        if len(matching) == 1:
            return matching[0]
        return None

    def _iter_path_ancestors(self, package_path: str) -> list[str]:
        ancestors = [package_path]
        current_path = package_path
        while current_path:
            if "/node_modules/" in current_path:
                current_path = current_path.rsplit("/node_modules/", 1)[0]
            elif current_path.startswith("node_modules/"):
                current_path = ""
            else:
                break
            ancestors.append(current_path)
        if "" not in ancestors:
            ancestors.append("")
        return ancestors

    def _parse_yarn_lock(self, content: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        in_dependencies = False

        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if not line.startswith(" "):
                if current is not None:
                    entries.append(current)
                selectors = [item.strip().strip('"').strip("'") for item in line[:-1].split(",")]
                current = {
                    "selectors": selectors,
                    "name": self._selector_name(selectors[0]),
                    "version": None,
                    "dependencies": {},
                }
                in_dependencies = False
                continue

            if current is None:
                continue

            stripped = line.strip()
            if stripped == "dependencies:":
                in_dependencies = True
                continue

            if line.startswith("  version "):
                current["version"] = stripped.removeprefix("version ").strip('"')
                in_dependencies = False
                continue

            if in_dependencies and line.startswith("    "):
                dependency_name, dependency_selector = stripped.split(" ", 1)
                current["dependencies"][dependency_name] = dependency_selector.strip('"')
                continue

            in_dependencies = False

        if current is not None:
            entries.append(current)

        return [entry for entry in entries if entry.get("version")]

    def _resolve_yarn_selector(
        self,
        *,
        name: str,
        requested_selector: str,
        selector_index: dict[str, dict[str, Any]],
    ) -> str | None:
        exact_selector = f"{name}@{requested_selector}"
        if exact_selector in selector_index:
            return exact_selector

        for selector in selector_index:
            if self._selector_name(selector) == name and self._selector_range(selector) == requested_selector:
                return selector

        matching = [
            selector
            for selector in selector_index
            if self._selector_name(selector) == name
        ]
        if len(matching) == 1:
            return matching[0]
        return None

    def _selector_name(self, selector: str) -> str:
        if selector.startswith("@"):
            return selector[: selector.find("@", 1)]
        package_name, _, _ = selector.partition("@")
        return package_name

    def _selector_range(self, selector: str) -> str:
        if selector.startswith("@"):
            return selector[selector.find("@", 1) + 1 :]
        return selector.partition("@")[2]

    def _package_name_from_path(self, package_path: str) -> str:
        if package_path.endswith("package.json"):
            package_path = package_path.removesuffix("/package.json")
        if package_path.endswith("/node_modules"):
            return package_path.rsplit("/", 1)[-1]
        if "/node_modules/" in package_path:
            return package_path.rsplit("/node_modules/", 1)[-1]
        return package_path.rsplit("/", 1)[-1]

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _merge_dependency_type(self, current: str, candidate: str) -> str:
        current_rank = DEPENDENCY_TYPE_RANK.get(current, 0)
        candidate_rank = DEPENDENCY_TYPE_RANK.get(candidate, 0)
        return current if current_rank >= candidate_rank else candidate

    def _sorted_unique(self, values: list[str]) -> list[str]:
        return sorted(dict.fromkeys(values))
