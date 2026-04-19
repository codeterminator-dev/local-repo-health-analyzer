from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from src.models import DependencySpec, ManifestParseResult
from src.parsers.requirements_parser import RequirementsParser


class SetupPyParser:
    def __init__(self) -> None:
        self._requirement_parser = RequirementsParser()

    def parse(self, path: str | Path) -> ManifestParseResult:
        target = Path(path).resolve()
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))

        symbols: dict[str, Any] = {}
        project_name: str | None = None
        dependencies: list[DependencySpec] = []

        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                value = self._safe_eval(statement.value, symbols)
                for assign_target in statement.targets:
                    if isinstance(assign_target, ast.Name) and value is not _UNRESOLVED:
                        symbols[assign_target.id] = value
            elif isinstance(statement, ast.AnnAssign):
                value = self._safe_eval(statement.value, symbols)
                if (
                    isinstance(statement.target, ast.Name)
                    and value is not _UNRESOLVED
                ):
                    symbols[statement.target.id] = value
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                parsed_name, parsed_dependencies = self._parse_setup_call(statement.value, symbols, target)
                if parsed_name:
                    project_name = parsed_name
                dependencies.extend(parsed_dependencies)

        return ManifestParseResult(project_name=project_name, dependencies=dependencies)

    def _parse_setup_call(
        self,
        call: ast.Call,
        symbols: dict[str, Any],
        manifest_path: Path,
    ) -> tuple[str | None, list[DependencySpec]]:
        if not isinstance(call.func, ast.Name) or call.func.id != "setup":
            return None, []

        kwargs: dict[str, Any] = {}
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            value = self._safe_eval(keyword.value, symbols)
            if value is not _UNRESOLVED:
                kwargs[keyword.arg] = value

        project_name = kwargs.get("name") if isinstance(kwargs.get("name"), str) else None
        dependencies: list[DependencySpec] = []

        dependencies.extend(
            self._coerce_dependencies(kwargs.get("install_requires"), manifest_path)
        )
        dependencies.extend(
            self._coerce_dependency_groups(kwargs.get("extras_require"), manifest_path)
        )
        dependencies.extend(
            self._coerce_dependencies(kwargs.get("setup_requires"), manifest_path, groups=("setup",))
        )
        dependencies.extend(
            self._coerce_dependencies(kwargs.get("tests_require"), manifest_path, groups=("test",))
        )
        return project_name, dependencies

    def _coerce_dependencies(
        self,
        value: Any,
        manifest_path: Path,
        *,
        groups: tuple[str, ...] = (),
    ) -> list[DependencySpec]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []

        dependencies: list[DependencySpec] = []
        for item in value:
            if not isinstance(item, str):
                continue
            dependency = self._requirement_parser._parse_requirement_line(item.strip(), manifest_path)
            if dependency is None:
                continue
            dependency.groups = tuple(sorted(set(dependency.groups).union(groups)))
            dependencies.append(dependency)
        return dependencies

    def _coerce_dependency_groups(
        self,
        value: Any,
        manifest_path: Path,
    ) -> list[DependencySpec]:
        if not isinstance(value, dict):
            return []

        dependencies: list[DependencySpec] = []
        for group_name, group_dependencies in value.items():
            if not isinstance(group_name, str):
                continue
            dependencies.extend(
                self._coerce_dependencies(
                    group_dependencies,
                    manifest_path,
                    groups=(f"extra:{group_name}",),
                )
            )
        return dependencies

    def _safe_eval(self, node: ast.AST | None, symbols: dict[str, Any]) -> Any:
        if node is None:
            return _UNRESOLVED
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return symbols.get(node.id, _UNRESOLVED)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values: list[Any] = []
            for element in node.elts:
                value = self._safe_eval(element, symbols)
                if value is _UNRESOLVED:
                    return _UNRESOLVED
                values.append(value)
            return values
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                key = self._safe_eval(key_node, symbols)
                value = self._safe_eval(value_node, symbols)
                if key is _UNRESOLVED or value is _UNRESOLVED:
                    return _UNRESOLVED
                result[key] = value
            return result
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._safe_eval(node.left, symbols)
            right = self._safe_eval(node.right, symbols)
            if left is _UNRESOLVED or right is _UNRESOLVED:
                return _UNRESOLVED
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            if isinstance(left, str) and isinstance(right, str):
                return left + right
        return _UNRESOLVED


_UNRESOLVED = object()

