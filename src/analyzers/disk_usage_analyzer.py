from __future__ import annotations

import heapq
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


VIRTUAL_ENV_NAMES = {"venv", ".venv", "env"}
PIP_CACHE_MARKERS = {(".cache", "pip"), ("pip-cache",)}
NPM_CACHE_NAMES = {".npm", "npm-cache"}


@dataclass(frozen=True, slots=True)
class DirectoryUsage:
    path: str
    size_bytes: int
    file_count: int
    directory_count: int
    category: str = "directory"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LargeFile:
    path: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiskUsageReport:
    project_root: str
    total_size_bytes: int
    file_count: int
    directory_count: int
    duplicate_file_count: int
    largest_directories: list[DirectoryUsage]
    large_files: list[LargeFile]
    virtual_environments: list[DirectoryUsage]
    node_modules: list[DirectoryUsage]
    caches: list[DirectoryUsage]
    category_totals: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "total_size_bytes": self.total_size_bytes,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "duplicate_file_count": self.duplicate_file_count,
            "largest_directories": [item.to_dict() for item in self.largest_directories],
            "large_files": [item.to_dict() for item in self.large_files],
            "virtual_environments": [item.to_dict() for item in self.virtual_environments],
            "node_modules": [item.to_dict() for item in self.node_modules],
            "caches": [item.to_dict() for item in self.caches],
            "category_totals": dict(self.category_totals),
        }


@dataclass(slots=True)
class _DirectoryFrame:
    path: Path
    iterator: os.ScandirIterator[str]
    category: str
    effective_file_category: str
    size_bytes: int = 0
    file_count: int = 0
    directory_count: int = 1


class DiskUsageAnalyzer:
    """Analyze project disk usage and identify common storage hotspots."""

    def __init__(
        self,
        *,
        large_file_threshold_bytes: int = 10 * 1024 * 1024,
        max_hotspots: int = 10,
        max_large_files: int = 20,
    ) -> None:
        self._large_file_threshold_bytes = large_file_threshold_bytes
        self._max_hotspots = max_hotspots
        self._max_large_files = max_large_files

    def analyze(self, project_path: str | Path) -> DiskUsageReport:
        root = Path(project_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"project path does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"project path is not a directory: {root}")

        directory_reports, large_files, duplicate_file_count = self._scan_directory(root)
        category_totals = {
            "virtual_environment_bytes": self._category_totals["virtual_environment"],
            "node_modules_bytes": self._category_totals["node_modules"],
            "cache_bytes": self._category_totals["pip_cache"] + self._category_totals["npm_cache"],
            "other_bytes": self._category_totals["other"],
        }
        root_report = directory_reports[root]

        virtual_environments = self._sort_directories(
            report for report in directory_reports.values() if report.category == "virtual_environment"
        )
        node_modules = self._sort_directories(
            report for report in directory_reports.values() if report.category == "node_modules"
        )
        caches = self._sort_directories(
            report
            for report in directory_reports.values()
            if report.category in {"pip_cache", "npm_cache"}
        )
        hotspots = self._sort_directories(
            report for path, report in directory_reports.items() if path != root
        )[: self._max_hotspots]

        return DiskUsageReport(
            project_root=str(root),
            total_size_bytes=root_report.size_bytes,
            file_count=root_report.file_count,
            directory_count=root_report.directory_count,
            duplicate_file_count=duplicate_file_count,
            largest_directories=hotspots,
            large_files=large_files,
            virtual_environments=virtual_environments,
            node_modules=node_modules,
            caches=caches,
            category_totals=category_totals,
        )

    def _scan_directory(
        self,
        root: Path,
    ) -> tuple[dict[Path, DirectoryUsage], list[LargeFile], int]:
        root_inode = self._inode_key(root.stat(follow_symlinks=False))
        seen_directories = {root_inode}
        seen_files: set[tuple[int, int]] = set()
        duplicate_file_count = 0
        directory_reports: dict[Path, DirectoryUsage] = {}
        large_files_heap: list[tuple[int, str]] = []
        self._category_totals = {
            "virtual_environment": 0,
            "node_modules": 0,
            "pip_cache": 0,
            "npm_cache": 0,
            "other": 0,
        }
        stack = [
            _DirectoryFrame(
                path=root,
                iterator=os.scandir(root),
                category="project",
                effective_file_category="other",
            )
        ]

        while stack:
            frame = stack[-1]
            try:
                entry = next(frame.iterator)
            except StopIteration:
                frame.iterator.close()
                report = DirectoryUsage(
                    path=str(frame.path),
                    size_bytes=frame.size_bytes,
                    file_count=frame.file_count,
                    directory_count=frame.directory_count,
                    category=frame.category,
                )
                directory_reports[frame.path] = report
                stack.pop()
                if stack:
                    parent = stack[-1]
                    parent.size_bytes += report.size_bytes
                    parent.file_count += report.file_count
                    parent.directory_count += report.directory_count
                continue

            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            mode = entry_stat.st_mode
            inode_key = self._inode_key(entry_stat)

            if stat.S_ISDIR(mode):
                if inode_key in seen_directories:
                    continue
                try:
                    iterator = os.scandir(entry.path)
                except OSError:
                    continue
                seen_directories.add(inode_key)
                child_path = Path(entry.path)
                child_category = self._classify_directory(root, child_path)
                stack.append(
                    _DirectoryFrame(
                        path=child_path,
                        iterator=iterator,
                        category=child_category,
                        effective_file_category=self._effective_file_category(
                            current=child_category,
                            parent=frame.effective_file_category,
                        ),
                    )
                )
                continue

            if not stat.S_ISREG(mode):
                continue

            if inode_key in seen_files:
                duplicate_file_count += 1
                continue

            seen_files.add(inode_key)
            frame.size_bytes += entry_stat.st_size
            frame.file_count += 1
            self._category_totals[frame.effective_file_category] += entry_stat.st_size

            if entry_stat.st_size >= self._large_file_threshold_bytes:
                self._remember_large_file(
                    large_files_heap,
                    LargeFile(path=entry.path, size_bytes=entry_stat.st_size),
                )

        large_files = [
            LargeFile(path=path, size_bytes=size_bytes)
            for size_bytes, path in sorted(
                large_files_heap,
                key=lambda item: (-item[0], item[1]),
            )
        ]
        return directory_reports, large_files, duplicate_file_count

    def _classify_directory(self, root: Path, path: Path) -> str:
        if path == root:
            return "project"

        if path.name == "node_modules":
            return "node_modules"

        if path.name in VIRTUAL_ENV_NAMES or (path / "pyvenv.cfg").exists():
            return "virtual_environment"

        relative_parts = path.relative_to(root).parts
        if relative_parts[-1:] and tuple(relative_parts[-1:]) in PIP_CACHE_MARKERS:
            return "pip_cache"
        if len(relative_parts) >= 2 and tuple(relative_parts[-2:]) in PIP_CACHE_MARKERS:
            return "pip_cache"
        if path.name in NPM_CACHE_NAMES:
            return "npm_cache"

        return "directory"

    def _remember_large_file(
        self,
        heap: list[tuple[int, str]],
        large_file: LargeFile,
    ) -> None:
        heap_item = (large_file.size_bytes, large_file.path)
        if self._max_large_files <= 0:
            return
        if len(heap) < self._max_large_files:
            heapq.heappush(heap, heap_item)
            return

        smallest = heap[0]
        if heap_item > smallest:
            heapq.heapreplace(heap, heap_item)

    def _sort_directories(self, reports) -> list[DirectoryUsage]:
        return sorted(reports, key=lambda item: (-item.size_bytes, item.path))

    def _effective_file_category(self, *, current: str, parent: str) -> str:
        if current in {"virtual_environment", "node_modules", "pip_cache", "npm_cache"}:
            return current
        return parent

    def _inode_key(self, entry_stat: os.stat_result) -> tuple[int, int]:
        return (entry_stat.st_dev, entry_stat.st_ino)
