from __future__ import annotations

from .models import DependencyGraph, LanguageReport


class DependencyGraphBuilder:
    """Merges language-level findings into a repository-wide dependency graph."""

    def build(self, reports: list[LanguageReport]) -> DependencyGraph:
        graph = DependencyGraph()
        for report in reports:
            for node in report.nodes:
                graph.add_node(node)
            for edge in report.edges:
                graph.add_edge(edge)
        return graph
