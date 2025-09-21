#!/usr/bin/env python3
"""
Real data test harness for legal analytics services
Tests services using live Elasticsearch data instead of mocks
"""

import asyncio
import logging
import sys
import os
from typing import Dict, Any, Optional, List
import json
from elasticsearch import AsyncElasticsearch

# Add the court-processor directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def create_es_client() -> AsyncElasticsearch:
    """Create connection to live Elasticsearch instance"""
    return AsyncElasticsearch(
        hosts=["http://localhost:9200"],
        request_timeout=30,
        max_retries=2,
        retry_on_timeout=True
    )

async def test_elasticsearch_connection():
    """Test basic ES connection and data availability"""
    logger.info("=== Testing Elasticsearch Connection ===")

    es = await create_es_client()
    try:
        # Test connection
        info = await es.info()
        logger.info(f"✅ Connected to Elasticsearch {info['version']['number']}")

        # Check document count
        count_response = await es.count(index="court-documents")
        doc_count = count_response["count"]
        logger.info(f"✅ Found {doc_count} court documents")

        # Get sample document
        search_response = await es.search(
            index="court-documents",
            body={"query": {"match_all": {}}, "size": 1}
        )

        if search_response["hits"]["hits"]:
            sample_doc = search_response["hits"]["hits"][0]["_source"]
            logger.info(f"✅ Sample document ID: {sample_doc.get('id')}")
            logger.info(f"✅ Document fields: {list(sample_doc.keys())}")

            # Check for critical fields
            required_fields = ["legal_citations", "legal_topics", "content_embedding"]
            for field in required_fields:
                if field in sample_doc:
                    value = sample_doc[field]
                    if field == "content_embedding" and isinstance(value, list):
                        logger.info(f"✅ {field}: {len(value)}-dimensional vector")
                    elif isinstance(value, list):
                        logger.info(f"✅ {field}: {len(value)} items")
                    else:
                        logger.info(f"✅ {field}: present")
                else:
                    logger.warning(f"⚠️  {field}: missing")

        return True

    except Exception as e:
        logger.error(f"❌ Elasticsearch connection failed: {e}")
        return False
    finally:
        await es.close()

async def test_related_case_service_real_data():
    """Test RelatedCaseService with real Elasticsearch data"""
    logger.info("=== Testing RelatedCaseService with Real Data ===")

    try:
        from legal_analytics.case_recommendations import RelatedCaseService

        es = await create_es_client()
        service = RelatedCaseService(es)
        logger.info("✅ RelatedCaseService initialized with real ES client")

        # Get a real document ID
        search_response = await es.search(
            index="court-documents",
            body={"query": {"match_all": {}}, "size": 1}
        )

        if not search_response["hits"]["hits"]:
            logger.error("❌ No documents found in Elasticsearch")
            return False

        real_doc_id = str(search_response["hits"]["hits"][0]["_source"]["id"])
        logger.info(f"✅ Using real document ID: {real_doc_id}")

        # Test graph building
        logger.info("Building recommendation graphs with real data...")
        await service.build_recommendation_graphs()
        logger.info("✅ Recommendation graphs built successfully")

        # Test network statistics
        stats = await service.get_network_statistics()
        logger.info(f"✅ Citation network: {stats['citation_network']['nodes']} nodes, {stats['citation_network']['edges']} edges")
        logger.info(f"✅ Topic network: {stats['topic_network']['nodes']} nodes, {stats['topic_network']['edges']} edges")
        logger.info(f"✅ Authority scores computed: {stats['authority_scores']['computed']}")

        # Test case recommendations
        logger.info(f"Getting recommendations for document {real_doc_id}...")
        recommendations = await service.get_related_cases(
            document_id=real_doc_id,
            max_recommendations=10,
            min_score_threshold=0.01,  # Lower threshold for real data
            include_full_graph=True
        )

        logger.info(f"✅ Found {len(recommendations.recommendations)} recommendations")
        logger.info(f"✅ Total candidates: {recommendations.total_candidates}")
        logger.info(f"✅ Citation network size: {len(recommendations.citation_network)}")
        logger.info(f"✅ Topic clusters: {len(recommendations.topic_clusters)}")

        # Print top recommendations
        for i, rec in enumerate(recommendations.recommendations[:3]):
            logger.info(f"✅ Recommendation {i+1}: {rec.document_id} "
                       f"(score: {rec.similarity_score:.3f}, "
                       f"reasons: {rec.recommendation_reasons})")

        await es.close()
        return True

    except Exception as e:
        logger.error(f"❌ RelatedCaseService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def test_topic_clustering_service_real_data():
    """Test TopicClusteringService with real Elasticsearch data"""
    logger.info("=== Testing TopicClusteringService with Real Data ===")

    try:
        from legal_analytics.topic_clustering import TopicClusteringService

        es = await create_es_client()
        service = TopicClusteringService(es)
        logger.info("✅ TopicClusteringService initialized with real ES client")

        # Test with smaller parameters for real data
        logger.info("Building topic clusters with real data...")
        clusters = await service.build_topic_clusters(
            min_cluster_size=2,
            max_clusters=5,  # Fewer clusters for initial test
            similarity_threshold=0.3
        )

        logger.info(f"✅ Found {len(clusters.clusters)} topic clusters")
        logger.info(f"✅ ClusterGraph object created successfully")

        # Print cluster details
        for i, cluster in enumerate(clusters.clusters[:3]):
            logger.info(f"✅ Cluster {i+1}: {cluster.name} "
                       f"({len(cluster.document_ids)} docs, "
                       f"coherence: {cluster.coherence_score:.3f})")

        # Test getting statistics
        stats = await service.get_clustering_statistics()
        logger.info(f"✅ Clustering statistics: {stats.keys()}")

        await es.close()
        return True

    except Exception as e:
        logger.error(f"❌ TopicClusteringService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def test_citation_analytics_service_real_data():
    """Test CitationAnalyticsService with real Elasticsearch data"""
    logger.info("=== Testing CitationAnalyticsService with Real Data ===")

    try:
        from legal_analytics.citation_analytics import CitationAnalyticsService

        es = await create_es_client()
        service = CitationAnalyticsService(es)
        logger.info("✅ CitationAnalyticsService initialized with real ES client")

        # Test citation network building
        logger.info("Building citation network with real data...")
        network = await service.build_citation_network()

        # Check the actual attributes of CitationNetwork
        logger.info(f"✅ CitationNetwork object created")
        logger.info(f"✅ Network type: {type(network)}")

        # Try to find the correct attributes
        network_attrs = [attr for attr in dir(network) if not attr.startswith('_')]
        logger.info(f"✅ Available attributes: {network_attrs}")

        # Try common attribute names
        if hasattr(network, 'citation_nodes'):
            logger.info(f"✅ Citation nodes: {len(network.citation_nodes)}")
        if hasattr(network, 'citation_edges'):
            logger.info(f"✅ Citation edges: {len(network.citation_edges)}")
        if hasattr(network, 'authority_scores'):
            logger.info(f"✅ Authority scores: {len(network.authority_scores)}")
        if hasattr(network, 'network_statistics'):
            logger.info(f"✅ Network statistics: {network.network_statistics}")

        # Get a real document for individual analysis
        search_response = await es.search(
            index="court-documents",
            body={"query": {"match_all": {}}, "size": 1}
        )

        if search_response["hits"]["hits"]:
            real_doc_id = str(search_response["hits"]["hits"][0]["_source"]["id"])

            # Test document citation analysis
            logger.info(f"Analyzing citations for document {real_doc_id}...")
            doc_analysis = await service.get_document_citation_analysis(real_doc_id)
            logger.info(f"✅ Document citation analysis completed")
            logger.info(f"✅ Analysis keys: {list(doc_analysis.keys())}")

        # Test citation statistics
        stats = await service.get_citation_statistics()
        logger.info(f"✅ Citation statistics: {list(stats.keys())}")

        await es.close()
        return True

    except Exception as e:
        logger.error(f"❌ CitationAnalyticsService test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def main():
    """Run all real data service tests"""
    logger.info("Starting real data service tests...")
    logger.info("Using live Elasticsearch at localhost:9200")

    # Test ES connection first
    es_ok = await test_elasticsearch_connection()
    if not es_ok:
        logger.error("❌ Cannot proceed without Elasticsearch connection")
        return False

    results = {
        "RelatedCaseService": await test_related_case_service_real_data(),
        "TopicClusteringService": await test_topic_clustering_service_real_data(),
        "CitationAnalyticsService": await test_citation_analytics_service_real_data()
    }

    logger.info("\n=== REAL DATA TEST RESULTS ===")
    all_passed = True
    for service_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{service_name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        logger.info("🎉 All services passed real data testing!")
    else:
        logger.info("⚠️  Some services failed with real data - see details above")

    return all_passed

if __name__ == "__main__":
    asyncio.run(main())