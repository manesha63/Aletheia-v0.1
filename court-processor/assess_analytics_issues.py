#!/usr/bin/env python3
"""
Analytics Issues Assessment Tool
Isolates and assesses current analytics problems for targeted fixes
"""

import asyncio
import logging
import sys
import os
from elasticsearch import AsyncElasticsearch

# Add the court-processor directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def create_es_client() -> AsyncElasticsearch:
    """Create connection to live Elasticsearch instance"""
    return AsyncElasticsearch(
        hosts=["http://localhost:9200"],
        request_timeout=60,
        max_retries=3,
        retry_on_timeout=True
    )

async def assess_topic_clustering_issue():
    """Assess why topic clustering produces 0 clusters"""
    logger.info("=== TOPIC CLUSTERING ASSESSMENT ===")

    try:
        from legal_analytics.topic_clustering import TopicClusteringService

        es = await create_es_client()
        service = TopicClusteringService(es)

        # Get basic clustering with minimal parameters
        logger.info("Testing topic clustering with minimal parameters...")
        clusters = await service.build_topic_clusters(
            min_cluster_size=1,  # Very low minimum - allows single-topic clusters
            max_clusters=10,     # Limited clusters
            similarity_threshold=0.1,  # Lower threshold
            use_semantic_clustering=True
        )

        logger.info(f"Clusters generated: {len(clusters.clusters)}")

        if len(clusters.clusters) == 0:
            logger.error("ISSUE ISOLATED: Topic clustering produces 0 clusters")
            logger.info("Checking for specific causes...")

            # Check if documents have embeddings
            sample_docs = await es.search(
                index="court-documents",
                body={
                    "query": {"exists": {"field": "content_embedding"}},
                    "size": 5,
                    "_source": ["id", "content_embedding"]
                }
            )

            if sample_docs["hits"]["hits"]:
                logger.info(f"Documents with embeddings: {sample_docs['hits']['total']['value']}")
                embedding_dims = len(sample_docs["hits"]["hits"][0]["_source"]["content_embedding"])
                logger.info(f"Embedding dimensions: {embedding_dims}")
                logger.error("DIAGNOSIS: Documents have embeddings but clustering fails - algorithm issue")
            else:
                logger.error("DIAGNOSIS: No documents have embeddings - data issue")
        else:
            logger.info("Topic clustering working correctly")

        await es.close()
        return len(clusters.clusters) == 0

    except Exception as e:
        logger.error(f"Topic clustering assessment failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return True

async def assess_citation_network_sparsity():
    """Assess citation network connectivity issues"""
    logger.info("=== CITATION NETWORK SPARSITY ASSESSMENT ===")

    try:
        from legal_analytics.citation_analytics import CitationAnalyticsService

        es = await create_es_client()
        service = CitationAnalyticsService(es)

        # Build citation network
        logger.info("Building citation network...")
        network = await service.build_citation_network()

        if hasattr(network, 'citation_graph'):
            graph = network.citation_graph
            nodes = len(graph.nodes())
            edges = len(graph.edges())

            logger.info(f"Citation network: {nodes} nodes, {edges} edges")

            if edges < nodes * 0.1:  # Less than 10% connectivity
                logger.error(f"ISSUE ISOLATED: Citation network is very sparse ({edges} edges for {nodes} nodes)")
                logger.error("DIAGNOSIS: Citations not properly linked between documents")

                # Check what types of nodes exist
                sample_nodes = list(graph.nodes())[:5]
                for node in sample_nodes:
                    node_data = graph.nodes[node]
                    logger.info(f"Sample node {node}: {node_data}")

                await es.close()
                return True
            else:
                logger.info("Citation network has reasonable connectivity")
                await es.close()
                return False
        else:
            logger.error("ISSUE ISOLATED: Citation graph not accessible")
            await es.close()
            return True

    except Exception as e:
        logger.error(f"Citation network assessment failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return True

async def assess_metadata_calculation_errors():
    """Assess metadata calculation issues"""
    logger.info("=== METADATA CALCULATION ASSESSMENT ===")

    es = await create_es_client()
    try:
        # Get a sample document to check metadata
        sample_doc = await es.search(
            index="court-documents",
            body={
                "query": {"match_all": {}},
                "size": 1,
                "_source": True
            }
        )

        if sample_doc["hits"]["hits"]:
            doc = sample_doc["hits"]["hits"][0]["_source"]
            doc_id = doc["id"]

            logger.info(f"Checking metadata for document {doc_id}")

            # Check content_length
            content = doc.get("content", "")
            actual_length = len(content)
            reported_length = doc.get("content_length", 0)

            logger.info(f"Content length - Actual: {actual_length}, Reported: {reported_length}")

            if actual_length > 0 and reported_length == 0:
                logger.error("ISSUE ISOLATED: content_length miscalculated")
                logger.error("DIAGNOSIS: Metadata calculation not reflecting actual content")

            # Check citation_count
            citations = doc.get("legal_citations", [])
            actual_citation_count = len(citations)
            reported_citation_count = doc.get("citation_count", 0)

            logger.info(f"Citation count - Actual: {actual_citation_count}, Reported: {reported_citation_count}")

            if actual_citation_count > 0 and reported_citation_count == 0:
                logger.error("ISSUE ISOLATED: citation_count miscalculated")
                logger.error("DIAGNOSIS: Citation metadata not reflecting actual citations")

            # Check topic_count
            topics = doc.get("legal_topics", [])
            actual_topic_count = len(topics)
            reported_topic_count = doc.get("topic_count", 0)

            logger.info(f"Topic count - Actual: {actual_topic_count}, Reported: {reported_topic_count}")

            if actual_topic_count > 0 and reported_topic_count == 0:
                logger.error("ISSUE ISOLATED: topic_count miscalculated")
                logger.error("DIAGNOSIS: Topic metadata not reflecting actual topics")

            metadata_issues = (
                (actual_length > 0 and reported_length == 0) or
                (actual_citation_count > 0 and reported_citation_count == 0) or
                (actual_topic_count > 0 and reported_topic_count == 0)
            )

            await es.close()
            return metadata_issues
        else:
            logger.error("No documents found for metadata assessment")
            await es.close()
            return True

    except Exception as e:
        logger.error(f"Metadata assessment failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await es.close()
        return True

async def assess_recommendations_quality():
    """Assess recommendation quality issues"""
    logger.info("=== RECOMMENDATIONS QUALITY ASSESSMENT ===")

    try:
        from legal_analytics.case_recommendations import RelatedCaseService

        es = await create_es_client()
        service = RelatedCaseService(es)

        # Get a sample document to test recommendations
        sample_doc = await es.search(
            index="court-documents",
            body={
                "query": {"match_all": {}},
                "size": 1,
                "_source": ["id"]
            }
        )

        if sample_doc["hits"]["hits"]:
            doc_id = str(sample_doc["hits"]["hits"][0]["_source"]["id"])

            logger.info(f"Testing recommendations for document {doc_id}")

            # Build recommendation graphs
            await service.build_recommendation_graphs()

            # Get recommendations
            recommendations = await service.get_related_cases(
                document_id=doc_id,
                max_recommendations=10,
                min_score_threshold=0.01,
                include_full_graph=True
            )

            logger.info(f"Recommendations returned: {len(recommendations.recommendations)}")

            if len(recommendations.recommendations) == 0:
                logger.error("ISSUE ISOLATED: No recommendations generated")
                logger.error("DIAGNOSIS: Recommendation algorithm failing to find similar cases")
                await es.close()
                return True

            # Check score distribution
            scores = [rec.similarity_score for rec in recommendations.recommendations]
            min_score = min(scores)
            max_score = max(scores)
            avg_score = sum(scores) / len(scores)

            logger.info(f"Score distribution - Min: {min_score:.3f}, Max: {max_score:.3f}, Avg: {avg_score:.3f}")

            if max_score - min_score < 0.05:  # Very narrow score range
                logger.error("ISSUE ISOLATED: Poor score discrimination")
                logger.error("DIAGNOSIS: Scoring algorithm producing uniform results")
                await es.close()
                return True

            logger.info("Recommendations quality appears reasonable")
            await es.close()
            return False

        else:
            logger.error("No documents found for recommendations testing")
            await es.close()
            return True

    except Exception as e:
        logger.error(f"Recommendations assessment failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return True

async def main():
    """Run targeted analytics assessments"""
    logger.info("Starting targeted analytics issues assessment...")

    issues_found = {
        "topic_clustering_failure": False,
        "citation_network_sparsity": False,
        "metadata_calculation_errors": False,
        "recommendations_quality": False
    }

    # Assess each major issue area
    issues_found["topic_clustering_failure"] = await assess_topic_clustering_issue()
    issues_found["citation_network_sparsity"] = await assess_citation_network_sparsity()
    issues_found["metadata_calculation_errors"] = await assess_metadata_calculation_errors()
    issues_found["recommendations_quality"] = await assess_recommendations_quality()

    # Summary
    logger.info("\n=== ASSESSMENT SUMMARY ===")
    total_issues = sum(issues_found.values())
    logger.info(f"Total issues identified: {total_issues}/4")

    for issue_name, has_issue in issues_found.items():
        status = "FOUND" if has_issue else "OK"
        logger.info(f"{issue_name}: {status}")

    if total_issues > 0:
        logger.info("\n=== ISOLATION SUCCESS ===")
        logger.info("Issues have been isolated and can be targeted for fixes")
    else:
        logger.info("\n=== NO CRITICAL ISSUES ===")
        logger.info("Analytics appear to be functioning correctly")

if __name__ == "__main__":
    asyncio.run(main())