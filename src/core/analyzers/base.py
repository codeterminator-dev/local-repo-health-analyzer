from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AnalysisArtifact, LanguageReport, ScanOptions


class LanguageAnalyzer(ABC):
    """Abstract contract for read-only language analyzers."""

    language: str

    @abstractmethod
    def detect(self, root_path: Path) -> bool:
        """Return whether the analyzer can process the repository."""

    @abstractmethod
    def discover(self, root_path: Path, options: ScanOptions) -> AnalysisArtifact:
        """Return manifests and source files eligible for analysis."""

    @abstractmethod
    def analyze(self, root_path: Path, options: ScanOptions) -> LanguageReport:
        """Produce a language report without modifying the repository."""
