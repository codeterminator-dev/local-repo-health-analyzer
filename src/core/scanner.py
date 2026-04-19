from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .analyzers.base import LanguageAnalyzer
from .dependency_graph import DependencyGraphBuilder
from .models import ScanOptions, ScanReport


class Scanner:
    """Coordinates read-only analyzers and builds a single dependency graph."""

    def __init__(
        self,
        analyzers: Iterable[LanguageAnalyzer],
        graph_builder: DependencyGraphBuilder | None = None,
    ) -> None:
        self._analyzers = tuple(analyzers)
        self._graph_builder = graph_builder or DependencyGraphBuilder()

    def scan(self, root_path: str | Path, options: ScanOptions | None = None) -> ScanReport:
        root = Path(root_path).resolve()
        scan_options = options or ScanOptions()
        reports = []
        warnings: list[str] = []

        for analyzer in self._analyzers:
            if scan_options.include_languages and analyzer.language not in scan_options.include_languages:
                continue
            report = analyzer.analyze(root, scan_options)
            if report.detected:
                reports.append(report)
            warnings.extend(report.warnings)

        dependency_graph = self._graph_builder.build(reports)
        return ScanReport(
            root_path=root,
            reports=reports,
            dependency_graph=dependency_graph,
            warnings=warnings,
        )
