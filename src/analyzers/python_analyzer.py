from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.models import DependencyGraph, DependencySpec
from src.parsers import PyProjectParser, RequirementsParser, SetupPyParser


class PythonAnalyzer:
    def __init__(self) -> None:
        self._requirements_parser = RequirementsParser()
        self._setup_parser = SetupPyParser()
        self._pyproject_parser = PyProjectParser()
        self._resolved_projects: dict[Path, str] = {}

    def analyze(self, target: str | Path) -> DependencyGraph:
        graph = DependencyGraph()
        self._resolved_projects.clear()
        self._analyze_project(Path(target), graph)
        return graph

    def _analyze_project(self, target: Path, graph: DependencyGraph) -> str:
        resolved_target = target.resolve()
        project_root = resolved_target if resolved_target.is_dir() else resolved_target.parent

        cached_name = self._resolved_projects.get(project_root)
        if cached_name is not None:
            return cached_name

        manifests = self._discover_manifests(resolved_target)
        parsed_manifests = [self._parse_manifest(path) for path in manifests]
        project_name = next(
            (
                manifest.project_name
                for manifest in parsed_manifests
                if manifest.project_name
            ),
            project_root.name,
        )

        self._resolved_projects[project_root] = project_name
        graph.add_node(
            project_name,
            dependency_type="project",
            path=str(project_root),
        )

        for manifest_path, parsed_manifest in zip(manifests, parsed_manifests, strict=True):
            for dependency in parsed_manifest.dependencies:
                if dependency.dependency_type == "path" and dependency.path:
                    self._add_local_dependency(
                        graph,
                        project_name,
                        dependency,
                        manifest_path,
                    )
                    continue
                graph.add_dependency(project_name, dependency)

        return project_name

    def _discover_manifests(self, target: Path) -> list[Path]:
        if target.is_file():
            return [target]

        manifests: list[Path] = []
        for filename in ("pyproject.toml", "setup.py"):
            candidate = target / filename
            if candidate.exists():
                manifests.append(candidate)

        manifests.extend(sorted(target.glob("requirements*.txt")))
        return manifests

    def _parse_manifest(self, manifest_path: Path):
        if manifest_path.name == "pyproject.toml":
            return self._pyproject_parser.parse(manifest_path)
        if manifest_path.name == "setup.py":
            return self._setup_parser.parse(manifest_path)
        return self._requirements_parser.parse(manifest_path)

    def _add_local_dependency(
        self,
        graph: DependencyGraph,
        project_name: str,
        dependency: DependencySpec,
        manifest_path: Path,
    ) -> None:
        local_target = (manifest_path.parent / dependency.path).resolve()
        local_name = self._analyze_project(local_target, graph) if local_target.exists() else dependency.name
        rewritten = replace(
            dependency,
            name=local_name,
            path=str(local_target) if local_target.exists() else dependency.path,
        )
        graph.add_dependency(project_name, rewritten)

