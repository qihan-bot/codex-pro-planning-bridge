"""Compatibility names for context-specific model imports."""

from ..models import FileInfo, ProjectContext

FileContext = FileInfo
RepositoryContext = ProjectContext

__all__ = ["FileContext", "ProjectContext", "RepositoryContext"]
