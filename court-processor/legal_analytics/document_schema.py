"""
Standardized Document Schema for Legal Analytics

Provides unified document field definitions and query builders to ensure
consistency across all analytics services and eliminate field mismatches.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

class DocumentProfile(Enum):
    """Document profiles for different analytics needs"""
    MINIMAL = "minimal"          # Core identification fields only
    BASIC = "basic"             # Common analytics fields
    CITATIONS = "citations"      # Citation analysis fields
    TOPICS = "topics"           # Topic clustering fields
    RECOMMENDATIONS = "recommendations"  # Case recommendation fields
    COMPLETE = "complete"       # All available fields

@dataclass
class DocumentFieldSet:
    """Defines which fields to fetch for different use cases"""

    # Core fields (always included)
    CORE_FIELDS = [
        "id", "case_name", "judge_name", "court_id",
        "filing_date", "document_type"
    ]

    # Extended field sets
    CITATION_FIELDS = CORE_FIELDS + [
        "legal_citations"
    ]

    TOPIC_FIELDS = CORE_FIELDS + [
        "legal_topics", "content_embedding", "content_length"
    ]

    RECOMMENDATION_FIELDS = CORE_FIELDS + [
        "legal_citations", "legal_topics", "case_dispositions",
        "content_embedding", "content_length"
    ]

    COMPLETE_FIELDS = CORE_FIELDS + [
        "legal_citations", "legal_topics", "case_dispositions",
        "content_embedding", "content_length", "precedent_strength",
        "outcome_type", "appeal_status"
    ]

    @classmethod
    def get_fields(cls, profile: DocumentProfile) -> List[str]:
        """Get field list for a specific document profile"""
        mapping = {
            DocumentProfile.MINIMAL: cls.CORE_FIELDS,
            DocumentProfile.BASIC: cls.CORE_FIELDS,
            DocumentProfile.CITATIONS: cls.CITATION_FIELDS,
            DocumentProfile.TOPICS: cls.TOPIC_FIELDS,
            DocumentProfile.RECOMMENDATIONS: cls.RECOMMENDATION_FIELDS,
            DocumentProfile.COMPLETE: cls.COMPLETE_FIELDS
        }
        return mapping.get(profile, cls.CORE_FIELDS)

class StandardizedQueryBuilder:
    """Builds consistent Elasticsearch queries across all services"""

    @staticmethod
    def build_batch_query(
        profile: DocumentProfile,
        batch_size: int = 100,
        custom_query: Optional[Dict[str, Any]] = None,
        min_confidence: float = 0.3
    ) -> Dict[str, Any]:
        """
        Build standardized batch query for document fetching

        Args:
            profile: Document profile defining which fields to fetch
            batch_size: Number of documents per batch
            custom_query: Custom query conditions (overrides match_all)
            min_confidence: Minimum confidence for topic filtering
        """

        # Build base query
        if custom_query:
            query = custom_query
        elif profile == DocumentProfile.TOPICS:
            # Special query for topic-based analytics
            query = {
                "nested": {
                    "path": "legal_topics",
                    "query": {
                        "range": {
                            "legal_topics.confidence": {"gte": min_confidence}
                        }
                    }
                }
            }
        else:
            query = {"match_all": {}}

        return {
            "query": query,
            "size": batch_size,
            "_source": DocumentFieldSet.get_fields(profile),
            "sort": [{"filing_date": {"order": "desc"}}]  # Consistent ordering
        }

class DocumentProcessor:
    """Standardized document processing utilities"""

    @staticmethod
    def extract_citations(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract and normalize citations from a document"""
        citations = doc.get("legal_citations", []) or []
        return [
            {
                "citation": cite.get("citation", "") if isinstance(cite, dict) else str(cite),
                "confidence": cite.get("confidence", 1.0) if isinstance(cite, dict) else 1.0,
                "type": cite.get("type", "unknown") if isinstance(cite, dict) else "unknown"
            }
            for cite in citations
            if cite  # Filter out empty citations
        ]

    @staticmethod
    def extract_topics(doc: Dict[str, Any], min_confidence: float = 0.5) -> List[Dict[str, Any]]:
        """Extract and normalize topics from a document"""
        topics = doc.get("legal_topics", []) or []
        return [
            {
                "topic": topic.get("topic", ""),
                "confidence": topic.get("confidence", 0.0),
                "category": topic.get("category", "general")
            }
            for topic in topics
            if isinstance(topic, dict)
            and topic.get("topic")
            and topic.get("confidence", 0.0) >= min_confidence
        ]

    @staticmethod
    def normalize_document(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize document structure across all services"""
        return {
            "id": str(doc.get("id", "")),
            "case_name": doc.get("case_name", ""),
            "judge_name": doc.get("judge_name", ""),
            "court_id": doc.get("court_id", ""),
            "filing_date": doc.get("filing_date"),
            "document_type": doc.get("document_type", "unknown"),
            "citations": DocumentProcessor.extract_citations(doc),
            "topics": DocumentProcessor.extract_topics(doc),
            "content_length": doc.get("content_length", 0),
            "content_embedding": doc.get("content_embedding", [])
        }

# Service-specific query builders
class ServiceQueryBuilder:
    """Pre-configured query builders for each analytics service"""

    @staticmethod
    def case_recommendations_query(batch_size: int = 100) -> Dict[str, Any]:
        return StandardizedQueryBuilder.build_batch_query(
            DocumentProfile.RECOMMENDATIONS,
            batch_size
        )

    @staticmethod
    def citation_analytics_query(batch_size: int = 100) -> Dict[str, Any]:
        return StandardizedQueryBuilder.build_batch_query(
            DocumentProfile.CITATIONS,
            batch_size
        )

    @staticmethod
    def topic_clustering_query(batch_size: int = 100, min_confidence: float = 0.3) -> Dict[str, Any]:
        return StandardizedQueryBuilder.build_batch_query(
            DocumentProfile.TOPICS,
            batch_size,
            min_confidence=min_confidence
        )