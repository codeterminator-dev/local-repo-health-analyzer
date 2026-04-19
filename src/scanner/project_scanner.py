from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable


PYTHON_MARKERS = frozenset(
    {
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    }
)
NODE_MARKERS = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
SKIP_DIRECTORIES = frozenset({".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules"})


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    name: str
    path: str
    project_types: tuple[str, ...]
    markers: tuple[str, ...]


class ProjectScanner:
    def __init__(
        self,
        root_path: str,
        *,
        skip_directories: Iterable[str] | None = None,
        follow_symlink_dirs: bool = False,
    ) -> None:
        normalized_root = self._normalize_path(root_path)
        if not os.path.isdir(normalized_root):
            raise ValueError(f"Root path does not exist or is not a directory: {root_path}")

        self.root_path = normalized_root
        self.skip_directories = frozenset(skip_directories or SKIP_DIRECTORIES)
        self.follow_symlink_dirs = follow_symlink_dirs

    def scan(self) -> list[ProjectInfo]:
        projects: list[ProjectInfo] = []
        visited: set[str] = set()
        self._scan_directory(self.root_path, projects, visited)
        projects.sort(key=lambda project: project.path)
        return projects

    def _scan_directory(self, current_path: str, projects: list[ProjectInfo], visited: set[str]) -> None:
        normalized_current = self._normalize_path(current_path)
        if not self._is_within_root(normalized_current):
            return
        if normalized_current in visited:
            return
        visited.add(normalized_current)

        marker_files: list[str] = []
        subdirectories: list[str] = []

        with os.scandir(normalized_current) as entries:
            for entry in entries:
                entry_path = self._normalize_path(entry.path)

                if entry.is_symlink():
                    if entry.is_dir(follow_symlinks=True):
                        if self.follow_symlink_dirs and self._is_safe_symlink_target(entry.path):
                            subdirectories.append(entry_path)
                        continue
                    if entry.is_file(follow_symlinks=True) and self._is_within_root(entry_path):
                        marker_files.append(entry.name)
                    continue

                if entry.is_file(follow_symlinks=False):
                    marker_files.append(entry.name)
                    continue

                if entry.is_dir(follow_symlinks=False) and entry.name not in self.skip_directories:
                    subdirectories.append(entry_path)

        project = self._detect_project(normalized_current, marker_files)
        if project is not None:
            projects.append(project)

        for subdirectory in subdirectories:
            self._scan_directory(subdirectory, projects, visited)

    def _detect_project(self, directory_path: str, filenames: Iterable[str]) -> ProjectInfo | None:
        filename_set = set(filenames)
        project_types: list[str] = []
        markers: list[str] = []

        python_markers = sorted(filename_set & PYTHON_MARKERS)
        node_markers = sorted(filename_set & NODE_MARKERS)

        if python_markers:
            project_types.append("python")
            markers.extend(python_markers)
        if node_markers:
            project_types.append("node")
            markers.extend(node_markers)

        if not project_types:
            return None

        return ProjectInfo(
            name=os.path.basename(directory_path) or directory_path,
            path=directory_path,
            project_types=tuple(project_types),
            markers=tuple(sorted(markers)),
        )

    def _normalize_path(self, path: str) -> str:
        return os.path.realpath(os.path.abspath(path))

    def _is_within_root(self, path: str) -> bool:
        try:
            return os.path.commonpath([self.root_path, path]) == self.root_path
        except ValueError:
            return False

    def _is_safe_symlink_target(self, path: str) -> bool:
        return self._is_within_root(self._normalize_path(path))
