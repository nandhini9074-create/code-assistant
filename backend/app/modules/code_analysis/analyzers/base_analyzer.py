"""
app/modules/code_analysis/analyzers/base_analyzer.py
Base class for intent-specific analyzers.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.modules.code_analysis.domain.analysis_domain import AnalysisResult
from app.modules.search.domain.search_domain import SearchContext


class BaseAnalyzer(ABC):
    """Abstract base class for all analyzers."""
    
    @abstractmethod
    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """Perform the analysis based on the context and retrieved chunks."""
        pass
