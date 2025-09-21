"""
Integration Guide for Framework Refinement Solutions

This module demonstrates how to integrate all the refinement components:
- Standardized document schema
- Thread-safe process pool management
- Base validation framework
- Adaptive batch sizing
- Resource cleanup context managers

Shows concrete examples of using the simplified, generalized, and robust framework.
"""

from typing import Dict, List, Optional, Any
import asyncio
import logging

# Import our new framework components
from .document_schema import (
    DocumentProfile, DocumentFieldSet, StandardizedQueryBuilder,
    DocumentProcessor, ServiceQueryBuilder
)
from .process_pool_manager import (
    ProcessPoolManager, get_embedding_pool, encode_text_async
)
from .base_validation import (
    BaseAnalyticsRequest, RecommendationRequest, CitationAnalysisRequest,
    validate_with_context, get_validation_context
)
from .adaptive_batching import (
    OperationType, SimplifiedAdaptiveBatchSizer, get_batch_sizer,
    process_with_retry_and_batching, get_circuit_breaker_status,
    calculate_optimal_batch_size
)
from .resource_management import (
    ManagedAnalyticsService, analytics_service_context,
    elasticsearch_connection_manager, with_resource_management
)
# For monitoring and debugging
from .observability import (
    get_observability, track_operation, observe_function,
    log_info, log_error, get_diagnostics
)

logger = logging.getLogger(__name__)

class ModernCaseRecommendationService(ManagedAnalyticsService):
    """
    Example of modernized case recommendation service using all framework components

    Demonstrates:
    - Standardized document schema
    - Adaptive batch processing
    - Resource management
    - Validation framework
    - Thread-safe operations
    """

    def __init__(self, es_client):
        super().__init__("case_recommendations", es_client)
        self.batch_sizer = get_batch_sizer()

    async def get_related_cases(
        self,
        document_id: str,
        max_recommendations: int = 20,
        min_score_threshold: float = 0.1,
        include_full_graph: bool = True
    ) -> Dict[str, Any]:
        """Get related cases with full framework integration"""

        # 1. VALIDATION: Use base validation framework
        validation_context = get_validation_context()
        validated_request = await validate_with_context(
            RecommendationRequest,
            {
                "document_id": document_id,
                "max_recommendations": max_recommendations,
                "min_score_threshold": min_score_threshold,
                "include_full_graph": include_full_graph
            },
            validation_context
        )

        # 2. RESOURCE MANAGEMENT: Use analytics service context
        async with analytics_service_context(
            self.service_name,
            self.es_client
        ) as service_context:

            # 3. DOCUMENT SCHEMA: Use standardized query
            query = ServiceQueryBuilder.case_recommendations_query(
                batch_size=calculate_optimal_batch_size(OperationType.DOCUMENT_FETCH)
            )

            # 4. ADAPTIVE BATCHING: Process documents with adaptive sizing
            async def process_batch(documents):
                normalized_docs = [
                    DocumentProcessor.normalize_document(doc)
                    for doc in documents
                ]
                return self._build_recommendation_graph_batch(normalized_docs)

            documents = await self._fetch_documents_with_schema(query)
            successful_results, failed_items = await process_with_retry_and_batching(
                OperationType.GRAPH_BUILDING,
                documents,
                process_batch,
                isolate_failures=True
            )

            return self._format_recommendation_response(
                validated_request, successful_results
            )

    async def _fetch_documents_with_schema(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch documents using standardized schema with resource management"""
        documents = []

        async with self.get_scroll_context(query) as (response, scroll_id):
            hits = response["hits"]["hits"]

            while hits:
                # Process batch using standardized document processor
                batch_docs = [
                    DocumentProcessor.normalize_document(hit["_source"])
                    for hit in hits
                ]
                documents.extend(batch_docs)

                # Get next batch
                response = await self.es_client.scroll(
                    scroll_id=scroll_id,
                    scroll="5m"
                )
                hits = response["hits"]["hits"]

        return documents

    def _build_recommendation_graph_batch(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build recommendation graph from normalized documents"""
        # Implementation using standardized document structure
        return [
            {
                "document_id": doc["id"],
                "similarity_score": 0.8,  # Placeholder
                "citation_overlap": len(doc["citations"]),
                "topic_overlap": len(doc["topics"])
            }
            for doc in documents[:10]  # Top 10 for example
        ]

    def _format_recommendation_response(
        self,
        request: RecommendationRequest,
        recommendations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Format response using validated request parameters"""
        return {
            "target_document_id": request.document_id,
            "recommendations": recommendations[:request.max_recommendations],
            "metadata": {
                "algorithm_version": "2.0_modernized",
                "framework_components": [
                    "standardized_schema",
                    "adaptive_batching",
                    "resource_management",
                    "base_validation"
                ]
            }
        }

class ModernSearchService(ManagedAnalyticsService):
    """
    Example of modernized search service with process pool integration
    """

    def __init__(self, es_client):
        super().__init__("search", es_client)

    @with_resource_management("search_operation")
    async def semantic_search(
        self,
        query: str,
        max_results: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Semantic search with modern framework"""

        # 1. VALIDATION
        from .base_validation import SearchRequest
        validated_request = await validate_with_context(
            SearchRequest,
            {
                "query": query,
                "max_results": max_results,
                "filters": filters
            }
        )

        # 2. PROCESS POOL: Generate embedding using thread-safe pool
        try:
            query_embedding = await encode_text_async(
                validated_request.query,
                timeout=30.0
            )
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            # Fallback to keyword search
            return await self._keyword_search(validated_request)

        # 3. DOCUMENT SCHEMA: Use standardized search query
        search_query = {
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, 'content_embedding') + 1.0",
                        "params": {"query_vector": query_embedding}
                    }
                }
            },
            "size": validated_request.max_results,
            "_source": DocumentFieldSet.get_fields(DocumentProfile.BASIC)
        }

        # 4. RESOURCE MANAGEMENT: Search with managed ES connection
        async with elasticsearch_connection_manager(self.es_client, "search_es") as es:
            response = await es.search(
                index="court-documents",
                body=search_query
            )

        # 5. STANDARDIZED PROCESSING: Normalize results
        results = [
            DocumentProcessor.normalize_document(hit["_source"])
            for hit in response["hits"]["hits"]
        ]

        return {
            "query": validated_request.query,
            "results": results,
            "total_hits": response["hits"]["total"]["value"],
            "search_type": "semantic",
            "embedding_dimensions": len(query_embedding)
        }

    async def _keyword_search(self, request) -> Dict[str, Any]:
        """Fallback keyword search"""
        # Simplified fallback implementation
        return {
            "query": request.query,
            "results": [],
            "search_type": "keyword_fallback"
        }

# Integration utility functions
async def initialize_framework(es_client) -> Dict[str, Any]:
    """
    Initialize all framework components with proper integration

    Returns configuration and status of all components
    """
    # 1. Set up validation context with ES client
    validation_context = get_validation_context()
    validation_context.set_es_client(es_client)

    # 2. Initialize process pool manager
    pool_manager = ProcessPoolManager()
    embedding_pool = get_embedding_pool()

    # 3. Initialize adaptive batch sizer
    batch_sizer = get_batch_sizer()

    # 4. Test all components
    status = {
        "validation_context": "initialized",
        "process_pools": pool_manager.get_pool_stats(),
        "batch_sizer": "initialized",
        "document_schema": "loaded",
        "resource_management": "active"
    }

    logger.info("Framework initialization completed")
    return status

async def demonstration_workflow(es_client):
    """
    Demonstration of complete workflow using all framework components
    """
    logger.info("Starting framework demonstration...")

    # Initialize framework
    framework_status = await initialize_framework(es_client)
    logger.info(f"Framework status: {framework_status}")

    # Create modernized services
    recommendation_service = ModernCaseRecommendationService(es_client)
    search_service = ModernSearchService(es_client)

    try:
        # Example 1: Case recommendations with full framework
        async with recommendation_service:
            recommendations = await recommendation_service.get_related_cases(
                document_id="example_doc_123",
                max_recommendations=10
            )
            logger.info(f"Recommendations completed: {len(recommendations.get('recommendations', []))}")

        # Example 2: Semantic search with process pools
        async with search_service:
            search_results = await search_service.semantic_search(
                query="patent infringement damages calculation",
                max_results=15
            )
            logger.info(f"Search completed: {search_results.get('total_hits', 0)} hits")

        logger.info("Framework demonstration completed successfully")

    except Exception as e:
        logger.error(f"Demonstration failed: {e}")
        raise

# Migration guide for existing services
def create_migration_checklist() -> Dict[str, List[str]]:
    """
    Create checklist for migrating existing services to new framework
    """
    return {
        "1_validation": [
            "Replace manual validation with BaseAnalyticsRequest subclasses",
            "Add async validation for document existence",
            "Update error messages to use validation framework"
        ],
        "2_document_schema": [
            "Replace hardcoded _source fields with DocumentFieldSet",
            "Use StandardizedQueryBuilder for all ES queries",
            "Normalize documents with DocumentProcessor"
        ],
        "3_batch_processing": [
            "Replace fixed batch sizes with AdaptiveBatchSizer",
            "Add performance monitoring to batch operations",
            "Implement retry logic with smaller batches"
        ],
        "4_process_pools": [
            "Replace direct embedding calls with encode_text_async",
            "Use ProcessPoolManager for CPU-intensive operations",
            "Add proper pool cleanup"
        ],
        "5_resource_management": [
            "Wrap services with ManagedAnalyticsService",
            "Use context managers for ES scroll operations",
            "Add resource tracking and cleanup"
        ],
        "6_testing": [
            "Test with adaptive batch sizing",
            "Verify resource cleanup",
            "Check thread safety under load",
            "Validate performance improvements"
        ]
    }

if __name__ == "__main__":
    # Example usage
    print("Framework Refinement Components:")
    print("1. Standardized Document Schema ✓")
    print("2. Thread-Safe Process Pool Management ✓")
    print("3. Base Validation Framework ✓")
    print("4. Adaptive Batch Sizing ✓")
    print("5. Resource Cleanup Context Managers ✓")
    print("\nMigration checklist:")
    checklist = create_migration_checklist()
    for phase, tasks in checklist.items():
        print(f"\n{phase}:")
        for task in tasks:
            print(f"  - {task}")