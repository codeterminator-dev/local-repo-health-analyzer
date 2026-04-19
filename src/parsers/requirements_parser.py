from __future__ import annotations

import re
from pathlib import Path

from src.models import DependencySpec, ManifestParseResult, merge_specifiers


INCLUDE_PATTERN = re.compile(r"^(?:-r|--requirement)\s+(?P<path>.+)$")
CONSTRAINT_PATTERN = re.compile(r"^(?:-c|--constraint)\s+(?P<path>.+)$")
EDITABLE_PATTERN = re.compile(r"^(?:-e|--editable)\s+(?P<target>.+)$")
OPTION_PATTERN = re.compile(r"^--?[A-Za-z0-9-]+(?:[= ].*)?$")
PEP508_URL_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[(?P<extras>[^\]]+)])?\s*@\s*(?P<url>\S+)$"
)
NAME_SPEC_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[(?P<extras>[^\]]+)])?\s*(?P<spec>.*)$"
)
VCS_PREFIXES = ("git+", "hg+", "svn+", "bzr+")


class RequirementsParser:
    def parse(self, path: str | Path) -> ManifestParseResult:
        target = Path(path).resolve()
        dependencies = self._parse_file(target, visited=set())
        return ManifestParseResult(project_name=None, dependencies=dependencies)

    def _parse_file(self, path: Path, visited: set[Path]) -> list[DependencySpec]:
        if path in visited or not path.exists():
            return []
        visited.add(path)

        dependencies: list[DependencySpec] = []
        constraints: dict[str, str] = {}

        for line in self._read_logical_lines(path):
            stripped = self._strip_inline_comment(line).strip()
            if not stripped:
                continue

            include_match = INCLUDE_PATTERN.match(stripped)
            if include_match:
                include_path = self._resolve_nested_path(path, include_match.group("path"))
                dependencies.extend(self._parse_file(include_path, visited))
                continue

            constraint_match = CONSTRAINT_PATTERN.match(stripped)
            if constraint_match:
                constraint_path = self._resolve_nested_path(path, constraint_match.group("path"))
                for dependency in self._parse_file(constraint_path, visited):
                    constraints[dependency.key] = merge_specifiers(
                        constraints.get(dependency.key, ""),
                        dependency.version_spec,
                    )
                continue

            if (
                OPTION_PATTERN.match(stripped)
                and not stripped.startswith(VCS_PREFIXES)
                and not EDITABLE_PATTERN.match(stripped)
            ):
                continue

            dependency = self._parse_requirement_line(stripped, path)
            if dependency is not None:
                dependency.version_spec = merge_specifiers(
                    dependency.version_spec,
                    constraints.get(dependency.key, ""),
                )
                dependencies.append(dependency)

        return dependencies

    def _read_logical_lines(self, path: Path) -> list[str]:
        logical_lines: list[str] = []
        current = ""
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.rstrip()
            if not line and not current:
                logical_lines.append("")
                continue

            if line.endswith("\\"):
                current += line[:-1].rstrip() + " "
                continue

            logical_lines.append(current + line)
            current = ""

        if current:
            logical_lines.append(current)
        return logical_lines

    def _strip_inline_comment(self, value: str) -> str:
        return re.sub(r"\s+#.*$", "", value)

    def _resolve_nested_path(self, source: Path, raw_path: str) -> Path:
        nested = raw_path.strip().strip("'\"")
        return (source.parent / nested).resolve()

    def _parse_requirement_line(self, line: str, manifest_path: Path) -> DependencySpec | None:
        editable_match = EDITABLE_PATTERN.match(line)
        editable = False
        if editable_match:
            editable = True
            line = editable_match.group("target").strip()

        requirement, marker = self._split_marker(line)

        url_match = PEP508_URL_PATTERN.match(requirement)
        if url_match:
            name = url_match.group("name")
            return DependencySpec(
                name=name,
                dependency_type=self._url_dependency_type(url_match.group("url")),
                version_spec="",
                marker=marker,
                editable=editable,
                manifest_path=str(manifest_path),
                raw=line,
                metadata={"url": url_match.group("url")},
            )

        if requirement.startswith(VCS_PREFIXES) or "://" in requirement:
            name = self._extract_vcs_name(requirement)
            if name is None:
                return None
            return DependencySpec(
                name=name,
                dependency_type=self._url_dependency_type(requirement),
                marker=marker,
                editable=editable,
                manifest_path=str(manifest_path),
                raw=line,
                metadata={"url": requirement},
            )

        if self._looks_like_path(requirement):
            path = requirement.strip()
            return DependencySpec(
                name=self._guess_name_from_path(path),
                dependency_type="path",
                path=path,
                marker=marker,
                editable=editable,
                manifest_path=str(manifest_path),
                raw=line,
            )

        match = NAME_SPEC_PATTERN.match(requirement)
        if not match:
            return None

        name = match.group("name")
        extras = match.group("extras")
        spec = self._normalize_specifier(match.group("spec"))
        metadata = {"extras": [extra.strip() for extra in extras.split(",")]} if extras else {}
        return DependencySpec(
            name=name,
            version_spec=spec,
            dependency_type="package",
            marker=marker,
            editable=editable,
            manifest_path=str(manifest_path),
            raw=line,
            metadata=metadata,
        )

    def _split_marker(self, requirement: str) -> tuple[str, str | None]:
        if ";" not in requirement:
            return requirement.strip(), None
        base, marker = requirement.split(";", 1)
        return base.strip(), marker.strip() or None

    def _url_dependency_type(self, value: str) -> str:
        return "vcs" if value.startswith(VCS_PREFIXES) else "url"

    def _extract_vcs_name(self, requirement: str) -> str | None:
        egg_match = re.search(r"[#&]egg=([^&]+)", requirement)
        if egg_match:
            return egg_match.group(1)
        if " @ " in requirement:
            return requirement.split(" @ ", 1)[0].strip()
        return None

    def _looks_like_path(self, value: str) -> bool:
        return value.startswith((".", "/", "~")) or value.startswith("file:") or value.endswith(
            (".whl", ".tar.gz", ".zip")
        )

    def _guess_name_from_path(self, value: str) -> str:
        cleaned = value.replace("file:", "").rstrip("/")
        name = Path(cleaned).name or Path(cleaned).parent.name
        return name or value

    def _normalize_specifier(self, value: str) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", "", value)
