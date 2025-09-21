"""
Legal Analytics Module

Generalized legal document analysis services optimized for RAG consumption.
Provides citation networks, topic clustering, and case recommendations.
"""

from .case_recommendations import RelatedCaseService
from .topic_clustering import TopicClusteringService
from .citation_analytics import CitationAnalyticsService

__all__ = [
    'RelatedCaseService',
    'TopicClusteringService',
    'CitationAnalyticsService'
]