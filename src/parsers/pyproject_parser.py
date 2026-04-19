from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from src.models import DependencySpec, ManifestParseResult
from src.parsers.requirements_parser import RequirementsParser


class PyProjectParser:
    def __init__(self) -> None:
        self._requirement_parser = RequirementsParser()

    def parse(self, path: str | Path) -> ManifestParseResult:
        target = Path(path).resolve()
        data = tomllib.loads(target.read_text(encoding="utf-8"))

        project_name = None
        dependencies: list[DependencySpec] = []

        project = data.get("project", {})
        if isinstance(project, dict):
            project_name = project.get("name") or project_name
            dependencies.extend(
                self._parse_pep621_dependencies(project.get("dependencies"), target)
            )

            optional_groups = project.get("optional-dependencies", {})
            if isinstance(optional_groups, dict):
                for group_name, group_dependencies in optional_groups.items():
                    dependencies.extend(
                        self._parse_pep621_dependencies(
                            group_dependencies,
                            target,
                            groups=(f"extra:{group_name}",),
                        )
                    )

        build_system = data.get("build-system", {})
        if isinstance(build_system, dict):
            dependencies.extend(
                self._parse_pep621_dependencies(
                    build_system.get("requires"),
                    target,
                    groups=("build-system",),
                )
            )

        poetry = data.get("tool", {}).get("poetry", {})
        if isinstance(poetry, dict):
            project_name = poetry.get("name") or project_name
            dependencies.extend(
                self._parse_poetry_table(poetry.get("dependencies"), target)
            )
            dependencies.extend(
                self._parse_poetry_table(
                    poetry.get("dev-dependencies"),
                    target,
                    groups=("group:dev",),
                )
            )

            poetry_groups = poetry.get("group", {})
            if isinstance(poetry_groups, dict):
                for group_name, group_config in poetry_groups.items():
                    if not isinstance(group_config, dict):
                        continue
                    dependencies.extend(
                        self._parse_poetry_table(
                            group_config.get("dependencies"),
                            target,
                            groups=(f"group:{group_name}",),
                        )
                    )

        return ManifestParseResult(project_name=project_name, dependencies=dependencies)

    def _parse_pep621_dependencies(
        self,
        values: Any,
        manifest_path: Path,
        *,
        groups: tuple[str, ...] = (),
    ) -> list[DependencySpec]:
        if not isinstance(values, list):
            return []

        dependencies: list[DependencySpec] = []
        for item in values:
            if not isinstance(item, str):
                continue
            dependency = self._requirement_parser._parse_requirement_line(item, manifest_path)
            if dependency is None:
                continue
            dependency.groups = tuple(sorted(set(dependency.groups).union(groups)))
            dependencies.append(dependency)
        return dependencies

    def _parse_poetry_table(
        self,
        values: Any,
        manifest_path: Path,
        *,
        groups: tuple[str, ...] = (),
    ) -> list[DependencySpec]:
        if not isinstance(values, dict):
            return []

        dependencies: list[DependencySpec] = []
        for name, value in values.items():
            if name == "python":
                continue
            dependency = self._parse_poetry_dependency(name, value, manifest_path)
            if dependency is None:
                continue
            dependency.groups = tuple(sorted(set(dependency.groups).union(groups)))
            dependencies.append(dependency)
        return dependencies

    def _parse_poetry_dependency(
        self,
        name: str,
        value: Any,
        manifest_path: Path,
    ) -> DependencySpec | None:
        if isinstance(value, str):
            return DependencySpec(
                name=name,
                version_spec=value.strip(),
                manifest_path=str(manifest_path),
                raw=f"{name} {value}",
            )

        if not isinstance(value, dict):
            return None

        if "path" in value:
            return DependencySpec(
                name=name,
                dependency_type="path",
                path=str(value["path"]),
                editable=bool(value.get("develop")),
                marker=value.get("markers"),
                manifest_path=str(manifest_path),
                raw=f"{name} {value}",
            )

        if "git" in value:
            version = str(value.get("rev") or value.get("branch") or value.get("tag") or "")
            return DependencySpec(
                name=name,
                dependency_type="vcs",
                version_spec=version,
                marker=value.get("markers"),
                manifest_path=str(manifest_path),
                raw=f"{name} {value}",
                metadata={"url": value["git"]},
            )

        if "url" in value:
            return DependencySpec(
                name=name,
                dependency_type="url",
                marker=value.get("markers"),
                manifest_path=str(manifest_path),
                raw=f"{name} {value}",
                metadata={"url": value["url"]},
            )

        return DependencySpec(
            name=name,
            version_spec=str(value.get("version", "")).strip(),
            marker=value.get("markers"),
            manifest_path=str(manifest_path),
            raw=f"{name} {value}",
        )

