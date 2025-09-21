"""
Modular AI Search Features for Legal Document Search

This module provides a feature-flag based system for activating advanced
Elasticsearch capabilities in a modular way. Features can be enabled/disabled
based on use case requirements and dataset size.
"""

from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
import logging
import asyncio
import concurrent.futures
from functools import lru_cache
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# Import validation models
try:
    from legal_analytics.validation import SearchRequest, validate_positive_integer
except ImportError:
    # Fallback validation functions if module not available
    def validate_positive_integer(value, name, min_val=1, max_val=1000):
        if not isinstance(value, int) or not min_val <= value <= max_val:
            raise ValueError(f"{name} must be between {min_val} and {max_val}")
        return value

# Global embedding model cache and process pool
_embedding_model = None
_embedding_executor = None

def get_embedding_model():
    """Get or initialize the sentence transformer model (lazy loading)"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Use the same model that was likely used for existing embeddings (384-dim)
            _embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            logger.info("Loaded sentence transformer model: all-MiniLM-L6-v2")
        except ImportError:
            logger.error("sentence-transformers not installed. Install with: pip install sentence-transformers")
            raise ImportError("sentence-transformers required for semantic search")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    return _embedding_model

def get_embedding_executor():
    """Get or create the process pool executor for CPU-intensive embedding operations"""
    global _embedding_executor
    if _embedding_executor is None:
        # Use a single worker to avoid memory duplication of the model
        _embedding_executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=1,
            initializer=_init_embedding_worker
        )
        logger.info("Initialized embedding process pool executor")
    return _embedding_executor

def _init_embedding_worker():
    """Initialize the embedding model in worker process"""
    # This runs in the worker process to initialize the model there
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

def _encode_text_worker(text: str) -> List[float]:
    """Worker function for encoding text (runs in process pool)"""
    model = get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()

class SearchFeature(Enum):
    """Available search features that can be enabled modularly"""
    BASIC_SEARCH = "basic_search"              # Traditional keyword search
    SEMANTIC_SEARCH = "semantic_search"        # Vector similarity search
    HYBRID_SEARCH = "hybrid_search"            # Combined keyword + semantic
    LEGAL_FILTERING = "legal_filtering"        # Topic/disposition filters
    CITATION_ANALYSIS = "citation_analysis"    # Citation network features
    JUDICIAL_PATTERNS = "judicial_patterns"    # Judge-specific insights
    OUTCOME_PREDICTION = "outcome_prediction"  # Case outcome analysis
    SMART_SUGGESTIONS = "smart_suggestions"    # AI-powered query expansion

@dataclass
class SearchConfig:
    """Configuration for search features and their parameters"""
    enabled_features: List[SearchFeature]

    # Hybrid search weights
    keyword_weight: float = 0.4
    semantic_weight: float = 0.6

    # Filtering thresholds
    min_topic_confidence: float = 0.5
    min_citation_relevance: float = 0.3

    # Performance settings
    max_vector_candidates: int = 1000
    enable_caching: bool = True

    # Legal-specific settings
    legal_domain_boost: float = 1.2
    jurisdiction_boost: float = 1.1

class AISearchEngine:
    """
    Modular AI-powered search engine for legal documents

    Features are activated based on configuration, allowing progressive
    enhancement from basic keyword search to advanced legal AI.
    """

    def __init__(self, es_client, config: SearchConfig):
        self.es = es_client
        self.config = config
        self.index_name = "court-documents"

        # Feature activation
        self._feature_handlers = {
            SearchFeature.BASIC_SEARCH: self._basic_search,
            SearchFeature.SEMANTIC_SEARCH: self._semantic_search,
            SearchFeature.HYBRID_SEARCH: self._hybrid_search,
            SearchFeature.LEGAL_FILTERING: self._add_legal_filters,
            SearchFeature.CITATION_ANALYSIS: self._add_citation_analysis,
            SearchFeature.JUDICIAL_PATTERNS: self._add_judicial_patterns,
            SearchFeature.OUTCOME_PREDICTION: self._add_outcome_prediction,
            SearchFeature.SMART_SUGGESTIONS: self._generate_suggestions
        }

        logger.info(f"AI Search Engine initialized with features: {[f.value for f in config.enabled_features]}")

    async def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform search using activated features

        Returns enhanced results based on enabled feature set
        """

        # Validate input parameters
        try:
            if not query or not isinstance(query, str):
                raise ValueError("Query must be a non-empty string")
            if len(query.strip()) == 0:
                raise ValueError("Query cannot be empty or whitespace only")
            if len(query) > 1000:
                raise ValueError("Query too long (max 1000 characters)")

            limit = validate_positive_integer(limit, "limit", 1, 100)
            offset = validate_positive_integer(offset, "offset", 0, 10000)

            # Sanitize query
            query = query.strip()

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid search parameters: {e}")
            raise ValueError(f"Invalid search parameters: {e}")

        # Build base query using highest priority enabled feature
        if SearchFeature.HYBRID_SEARCH in self.config.enabled_features:
            search_query = await self._hybrid_search(query)
        elif SearchFeature.SEMANTIC_SEARCH in self.config.enabled_features:
            search_query = await self._semantic_search(query)
        else:
            search_query = self._basic_search(query)

        # Build complete search body
        search_body = {
            "query": search_query,
            "from": offset,
            "size": limit,
            "highlight": {
                "fields": {
                    "content": {"fragment_size": 150, "number_of_fragments": 2}
                }
            },
            "sort": ["_score", {"synced_at": {"order": "desc"}}]
        }

        # Add legal intelligence features
        if SearchFeature.LEGAL_FILTERING in self.config.enabled_features:
            search_body["aggs"] = self._add_legal_aggregations()
            if filters:
                search_body["query"] = self._apply_legal_filters(search_body["query"], filters)

        # Execute search
        response = await self.es.search(index=self.index_name, body=search_body)

        # Post-process results with activated features
        results = self._process_results(response, query)

        # Add feature-specific enhancements
        if SearchFeature.CITATION_ANALYSIS in self.config.enabled_features:
            results = await self._enhance_with_citations(results)

        if SearchFeature.JUDICIAL_PATTERNS in self.config.enabled_features:
            results = await self._enhance_with_judicial_patterns(results)

        if SearchFeature.OUTCOME_PREDICTION in self.config.enabled_features:
            results = await self._enhance_with_outcome_prediction(results)

        return results

    def _basic_search(self, query: str) -> Dict[str, Any]:
        """Traditional keyword search (baseline)"""
        return {
            "multi_match": {
                "query": query,
                "fields": ["content^2", "case_name", "formatted_title", "preview"],
                "type": "best_fields",
                "fuzziness": "AUTO"
            }
        }

    async def _semantic_search(self, query: str) -> Dict[str, Any]:
        """Vector similarity search using embeddings"""
        try:
            # Get query embedding using sentence-transformers
            query_embedding = await self._get_query_embedding(query)

            return {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": """
                            if (doc['content_embedding'].size() == 0) {
                                return 0.0;
                            }
                            return cosineSimilarity(params.query_vector, 'content_embedding') + 1.0;
                        """,
                        "params": {
                            "query_vector": query_embedding
                        }
                    }
                }
            }
        except Exception as e:
            logger.warning(f"Semantic search failed, falling back to match_all: {e}")
            # Fallback to simple match if embedding fails
            return {"match_all": {}}

    async def _get_query_embedding(self, query: str) -> List[float]:
        """Get embedding for query text using sentence transformers in process pool"""
        try:
            # Use process pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            executor = get_embedding_executor()
            embedding = await loop.run_in_executor(executor, _encode_text_worker, query)

            logger.debug(f"Generated embedding for query '{query[:50]}...': {len(embedding)} dimensions")
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding for query '{query[:50]}...': {e}")
            # Return empty embedding as fallback (will cause search to skip semantic component)
            return []

    async def _hybrid_search(self, query: str) -> Dict[str, Any]:
        """Combined keyword + semantic search with configurable weights"""
        keyword_query = self._basic_search(query)
        semantic_query = await self._semantic_search(query)

        return {
            "bool": {
                "should": [
                    {**keyword_query, "boost": self.config.keyword_weight},
                    {**semantic_query, "boost": self.config.semantic_weight}
                ]
            }
        }

    def _add_legal_aggregations(self) -> Dict[str, Any]:
        """Add legal intelligence aggregations for faceted search"""
        return {
            "legal_topics": {
                "nested": {"path": "legal_topics"},
                "aggs": {
                    "topics": {
                        "terms": {"field": "legal_topics.topic.keyword", "size": 20},
                        "aggs": {
                            "avg_confidence": {"avg": {"field": "legal_topics.confidence"}}
                        }
                    }
                }
            },
            "courts": {
                "terms": {"field": "court_id.keyword", "size": 15}
            },
            "judges": {
                "terms": {"field": "judge_name.keyword", "size": 20}
            },
            "dispositions": {
                "nested": {"path": "case_dispositions"},
                "aggs": {
                    "outcomes": {
                        "terms": {"field": "case_dispositions.disposition.keyword", "size": 10}
                    }
                }
            },
            "time_periods": {
                "date_histogram": {
                    "field": "filing_date",
                    "calendar_interval": "year"
                }
            }
        }

    def _apply_legal_filters(self, base_query: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
        """Apply legal domain filters to search query"""
        bool_query = {"bool": {"must": [base_query], "filter": []}}

        # Topic filtering with confidence threshold
        if "legal_topics" in filters:
            bool_query["bool"]["filter"].append({
                "nested": {
                    "path": "legal_topics",
                    "query": {
                        "bool": {
                            "must": [
                                {"terms": {"legal_topics.topic.keyword": filters["legal_topics"]}},
                                {"range": {"legal_topics.confidence": {"gte": self.config.min_topic_confidence}}}
                            ]
                        }
                    }
                }
            })

        # Court/jurisdiction filtering
        if "courts" in filters:
            bool_query["bool"]["filter"].append({
                "terms": {"court_id.keyword": filters["courts"]}
            })

        # Judge filtering
        if "judges" in filters:
            bool_query["bool"]["filter"].append({
                "terms": {"judge_name.keyword": filters["judges"]}
            })

        # Date range filtering
        if "date_range" in filters:
            bool_query["bool"]["filter"].append({
                "range": {
                    "filing_date": {
                        "gte": filters["date_range"]["start"],
                        "lte": filters["date_range"]["end"]
                    }
                }
            })

        # Case disposition filtering
        if "dispositions" in filters:
            bool_query["bool"]["filter"].append({
                "nested": {
                    "path": "case_dispositions",
                    "query": {
                        "terms": {"case_dispositions.disposition.keyword": filters["dispositions"]}
                    }
                }
            })

        return bool_query

    def _process_results(self, es_response: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Process ES results into standardized format with feature enhancements"""
        hits = es_response["hits"]["hits"]

        results = {
            "total": es_response["hits"]["total"]["value"] if isinstance(es_response["hits"]["total"], dict) else es_response["hits"]["total"],
            "returned": len(hits),
            "query": query,
            "documents": [],
            "aggregations": es_response.get("aggregations", {}),
            "features_used": [f.value for f in self.config.enabled_features]
        }

        for hit in hits:
            source = hit["_source"]
            doc = {
                "id": source["id"],
                "case": source.get("case_number", "Unknown"),
                "type": source.get("document_type", "unknown"),
                "judge": source.get("judge_name", "Unknown"),
                "court": source.get("court_id", "unknown"),
                "date_filed": source.get("filing_date") or source.get("decision_date"),
                "text_length": source.get("content_length", 0),
                "score": hit["_score"],
                "preview": self._extract_preview(hit),
                "formatted_title": source.get("formatted_title", f"Document {source['id']}"),
                "formatted_title_short": source.get("formatted_title_short"),
                "document_type_extracted": source.get("document_type_extracted"),
                "citation_components": {
                    "case_name": source.get("case_name"),
                    "document_type": source.get("document_type_extracted"),
                    "judge": source.get("judge_name"),
                    "date_filed": source.get("filing_date"),
                    "court": source.get("court_id")
                }
            }

            # Add legal intelligence data if available
            if SearchFeature.LEGAL_FILTERING in self.config.enabled_features:
                doc["legal_topics"] = source.get("legal_topics", [])
                doc["case_dispositions"] = source.get("case_dispositions", [])
                doc["legal_citations"] = source.get("legal_citations", [])

            results["documents"].append(doc)

        return results

    def _extract_preview(self, hit: Dict[str, Any]) -> str:
        """Extract preview with highlighting if available"""
        highlights = hit.get("highlight", {}).get("content", [])
        if highlights:
            return " ... ".join(highlights)
        return hit["_source"].get("preview", "")

    async def _enhance_with_citations(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Add citation network analysis"""
        # Placeholder for citation analysis
        results["citation_insights"] = {
            "total_citations": 0,
            "most_cited_cases": [],
            "citation_network_strength": 0.0
        }
        return results

    async def _enhance_with_judicial_patterns(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Add judicial pattern analysis"""
        # Placeholder for judicial pattern analysis
        results["judicial_insights"] = {
            "judge_trends": {},
            "court_patterns": {},
            "precedent_analysis": {}
        }
        return results

    async def _enhance_with_outcome_prediction(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Add outcome prediction analysis"""
        # Placeholder for outcome prediction
        results["outcome_insights"] = {
            "predicted_outcomes": [],
            "confidence_scores": [],
            "similar_cases": []
        }
        return results

    def cleanup(self):
        """Cleanup resources including process pool executor"""
        global _embedding_executor
        if _embedding_executor is not None:
            _embedding_executor.shutdown(wait=True)
            _embedding_executor = None
            logger.info("Cleaned up embedding process pool executor")

# Pre-configured feature sets for different use cases
class SearchProfiles:
    """Pre-configured search profiles for different use cases"""

    @staticmethod
    def basic() -> SearchConfig:
        """Basic keyword search - minimal resources"""
        return SearchConfig(
            enabled_features=[SearchFeature.BASIC_SEARCH]
        )

    @staticmethod
    def professional() -> SearchConfig:
        """Professional legal research - balanced features"""
        return SearchConfig(
            enabled_features=[
                SearchFeature.HYBRID_SEARCH,
                SearchFeature.LEGAL_FILTERING,
                SearchFeature.SMART_SUGGESTIONS
            ]
        )

    @staticmethod
    def advanced() -> SearchConfig:
        """Advanced legal AI - full feature set"""
        return SearchConfig(
            enabled_features=[
                SearchFeature.HYBRID_SEARCH,
                SearchFeature.LEGAL_FILTERING,
                SearchFeature.CITATION_ANALYSIS,
                SearchFeature.JUDICIAL_PATTERNS,
                SearchFeature.OUTCOME_PREDICTION,
                SearchFeature.SMART_SUGGESTIONS
            ]
        )

    @staticmethod
    def research_focused() -> SearchConfig:
        """Research-focused with citation analysis"""
        return SearchConfig(
            enabled_features=[
                SearchFeature.HYBRID_SEARCH,
                SearchFeature.LEGAL_FILTERING,
                SearchFeature.CITATION_ANALYSIS
            ],
            semantic_weight=0.7,  # Higher semantic weight for research
            min_citation_relevance=0.2
        )

    @staticmethod
    def litigation_support() -> SearchConfig:
        """Litigation support with outcome prediction"""
        return SearchConfig(
            enabled_features=[
                SearchFeature.HYBRID_SEARCH,
                SearchFeature.LEGAL_FILTERING,
                SearchFeature.JUDICIAL_PATTERNS,
                SearchFeature.OUTCOME_PREDICTION
            ],
            legal_domain_boost=1.3
        )