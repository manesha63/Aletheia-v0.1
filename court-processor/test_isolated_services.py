#!/usr/bin/env python3
"""
Isolated test harness for legal analytics services
Tests individual services without full API dependencies
"""

import asyncio
import logging
import sys
import os
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock
import json

# Add the court-processor directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MockElasticsearchClient:
    """Mock Elasticsearch client for isolated testing"""

    def __init__(self):
        self.mock_data = self._create_mock_data()

    def _create_mock_data(self) -> Dict[str, Any]:
        """Create realistic mock data for testing"""
        return {
            "documents": [
                {
                    "id": "doc1",
                    "case_name": "Smith v. Johnson",
                    "judge_name": "Judge Anderson",
                    "court_id": "COURT_001",
                    "filing_date": "2023-01-15",
                    "legal_citations": [
                        {"citation": "123 F.3d 456", "confidence": 0.9},
                        {"citation": "Brown v. Board", "confidence": 0.8}
                    ],
                    "legal_topics": [
                        {"topic": "contract_law", "confidence": 0.85},
                        {"topic": "commercial_disputes", "confidence": 0.75}
                    ],
                    "case_dispositions": ["dismissed"],
                    "content_embedding": [0.1] * 384,  # 384-dimensional embedding
                    "document_type": "court_filing",
                    "content_length": 1500
                },
                {
                    "id": "doc2",
                    "case_name": "Brown v. Davis",
                    "judge_name": "Judge Anderson",
                    "court_id": "COURT_001",
                    "filing_date": "2023-02-20",
                    "legal_citations": [
                        {"citation": "123 F.3d 456", "confidence": 0.8},
                        {"citation": "Williams v. State", "confidence": 0.9}
                    ],
                    "legal_topics": [
                        {"topic": "contract_law", "confidence": 0.9},
                        {"topic": "liability", "confidence": 0.7}
                    ],
                    "case_dispositions": ["settled"],
                    "content_embedding": [0.15] * 384,
                    "document_type": "court_filing",
                    "content_length": 2100
                },
                {
                    "id": "doc3",
                    "case_name": "Wilson v. Corporation",
                    "judge_name": "Judge Martinez",
                    "court_id": "COURT_002",
                    "filing_date": "2023-03-10",
                    "legal_citations": [
                        {"citation": "Brown v. Board", "confidence": 0.95}
                    ],
                    "legal_topics": [
                        {"topic": "employment_law", "confidence": 0.8},
                        {"topic": "discrimination", "confidence": 0.85}
                    ],
                    "case_dispositions": ["pending"],
                    "content_embedding": [0.2] * 384,
                    "document_type": "court_filing",
                    "content_length": 1800
                }
            ]
        }

    async def search(self, index: str, body: Dict[str, Any], scroll: Optional[str] = None) -> Dict[str, Any]:
        """Mock search method"""
        logger.info(f"Mock ES search called with query: {json.dumps(body, indent=2)}")

        # Handle scroll requests
        if scroll:
            return {
                "_scroll_id": "mock_scroll_id_123",
                "hits": {
                    "hits": [
                        {"_source": doc} for doc in self.mock_data["documents"]
                    ]
                }
            }

        # Handle different query types
        query = body.get("query", {})
        size = body.get("size", 10)

        # Match all query
        if "match_all" in query:
            hits = [{"_source": doc} for doc in self.mock_data["documents"]][:size]
            return {"hits": {"hits": hits}}

        # Terms query (fetch by IDs)
        if "terms" in query and "id" in query["terms"]:
            requested_ids = query["terms"]["id"]
            hits = [
                {"_source": doc} for doc in self.mock_data["documents"]
                if doc["id"] in requested_ids
            ][:size]
            return {"hits": {"hits": hits}}

        # Nested query for legal topics
        if "nested" in query and query["nested"].get("path") == "legal_topics":
            # Return documents with matching topics
            hits = [{"_source": doc} for doc in self.mock_data["documents"][:size]]
            return {"hits": {"hits": hits}}

        # Script score query (semantic similarity)
        if "script_score" in query:
            hits = [{"_source": doc} for doc in self.mock_data["documents"][:size]]
            return {"hits": {"hits": hits}}

        # Bool query for judicial similarity
        if "bool" in query:
            hits = [{"_source": doc} for doc in self.mock_data["documents"][:size]]
            return {"hits": {"hits": hits}}

        # Default: return all documents
        hits = [{"_source": doc} for doc in self.mock_data["documents"][:size]]
        return {"hits": {"hits": hits}}

    async def scroll(self, scroll_id: str, scroll: str) -> Dict[str, Any]:
        """Mock scroll method - return empty to end scrolling"""
        return {"hits": {"hits": []}}

    async def clear_scroll(self, scroll_id: str) -> Dict[str, Any]:
        """Mock clear scroll method"""
        return {"acknowledged": True}

async def test_related_case_service():
    """Test RelatedCaseService in isolation"""
    logger.info("=== Testing RelatedCaseService ===")

    try:
        # Import the service
        from legal_analytics.case_recommendations import RelatedCaseService

        # Create mock ES client
        mock_es = MockElasticsearchClient()

        # Initialize service
        service = RelatedCaseService(mock_es)
        logger.info("✅ RelatedCaseService initialized successfully")

        # Test graph building
        logger.info("Building recommendation graphs...")
        await service.build_recommendation_graphs()
        logger.info("✅ Recommendation graphs built successfully")

        # Test network statistics
        logger.info("Getting network statistics...")
        stats = await service.get_network_statistics()
        logger.info(f"✅ Network statistics: {json.dumps(stats, indent=2)}")

        # Test getting related cases - use min_confidence instead of min_score_threshold
        logger.info("Testing case recommendations...")
        recommendations = await service.get_related_cases(
            document_id="doc1",
            max_recommendations=5,
            min_score_threshold=0.1,  # Keep original parameter name for the service method
            include_full_graph=True
        )

        logger.info(f"✅ Found {len(recommendations.recommendations)} recommendations")
        logger.info(f"✅ Total candidates: {recommendations.total_candidates}")
        logger.info(f"✅ Citation network size: {len(recommendations.citation_network)}")
        logger.info(f"✅ Topic clusters: {len(recommendations.topic_clusters)}")

        # Print first recommendation details
        if recommendations.recommendations:
            first_rec = recommendations.recommendations[0]
            logger.info(f"✅ First recommendation: {first_rec.document_id} "
                       f"(score: {first_rec.similarity_score:.3f}, "
                       f"reasons: {first_rec.recommendation_reasons})")

        return True

    except Exception as e:
        logger.error(f"❌ RelatedCaseService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def test_topic_clustering_service():
    """Test TopicClusteringService in isolation"""
    logger.info("=== Testing TopicClusteringService ===")

    try:
        # Import the service
        from legal_analytics.topic_clustering import TopicClusteringService

        # Create mock ES client
        mock_es = MockElasticsearchClient()

        # Initialize service
        service = TopicClusteringService(mock_es)
        logger.info("✅ TopicClusteringService initialized successfully")

        # Test clustering - use build_topic_clusters method
        logger.info("Testing topic clustering...")
        clusters = await service.build_topic_clusters(
            min_cluster_size=2,
            max_clusters=10,
            similarity_threshold=0.3
        )

        logger.info(f"✅ Found {len(clusters.clusters)} topic clusters")
        logger.info(f"✅ Total documents processed: {clusters.total_documents}")
        logger.info(f"✅ Computation time: {clusters.computation_metadata.get('computation_time_seconds', 'N/A')}")

        # Print cluster details
        for i, cluster in enumerate(clusters.clusters[:3]):  # Show first 3 clusters
            logger.info(f"✅ Cluster {i+1}: {cluster.name} "
                       f"({len(cluster.document_ids)} docs, "
                       f"coherence: {cluster.coherence_score:.3f})")

        return True

    except Exception as e:
        logger.error(f"❌ TopicClusteringService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def test_citation_analytics_service():
    """Test CitationAnalyticsService in isolation"""
    logger.info("=== Testing CitationAnalyticsService ===")

    try:
        # Import the service
        from legal_analytics.citation_analytics import CitationAnalyticsService

        # Create mock ES client
        mock_es = MockElasticsearchClient()

        # Initialize service
        service = CitationAnalyticsService(mock_es)
        logger.info("✅ CitationAnalyticsService initialized successfully")

        # Test citation network analysis - use build_citation_network method
        logger.info("Testing citation network analysis...")
        network = await service.build_citation_network()

        logger.info(f"✅ Citation network has {len(network.nodes)} nodes")
        logger.info(f"✅ Citation network has {len(network.edges)} edges")
        logger.info(f"✅ Authority scores computed: {len(network.authority_scores)}")

        # Print top authorities
        if network.authority_scores:
            top_authorities = sorted(network.authority_scores.items(),
                                   key=lambda x: x[1], reverse=True)[:3]
            for doc_id, score in top_authorities:
                logger.info(f"✅ Top authority: {doc_id} (score: {score:.3f})")

        return True

    except Exception as e:
        logger.error(f"❌ CitationAnalyticsService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def main():
    """Run all isolated service tests"""
    logger.info("Starting isolated service tests...")

    results = {
        "RelatedCaseService": await test_related_case_service(),
        "TopicClusteringService": await test_topic_clustering_service(),
        "CitationAnalyticsService": await test_citation_analytics_service()
    }

    logger.info("\n=== TEST RESULTS SUMMARY ===")
    all_passed = True
    for service_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{service_name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        logger.info("🎉 All services passed isolated testing!")
    else:
        logger.info("⚠️  Some services failed - see details above")

    return all_passed

if __name__ == "__main__":
    asyncio.run(main())