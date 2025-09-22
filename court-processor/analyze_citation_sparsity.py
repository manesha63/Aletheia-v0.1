#!/usr/bin/env python3
"""
Citation Network Sparsity Analysis
==================================

Deep analysis of the remaining citation network sparsity issue:
- Current: 12 edges for 222 nodes (0.02% density)
- Expected: Much higher connectivity for meaningful legal analytics

This analysis identifies specific causes and solution approaches.
"""

import asyncio
import sys
import os
from elasticsearch import AsyncElasticsearch

# Add the court-processor directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

async def analyze_citation_sparsity():
    """Analyze citation network sparsity in detail"""

    es = AsyncElasticsearch(
        hosts=["http://localhost:9200"],
        request_timeout=60,
        max_retries=3,
        retry_on_timeout=True
    )

    try:
        print("=== CITATION NETWORK SPARSITY ANALYSIS ===")

        # Step 1: Analyze citation distribution across documents
        print("\n1. CITATION DISTRIBUTION ANALYSIS")

        # Get documents with citations
        docs_with_citations = await es.search(
            index="court-documents",
            body={
                "query": {"exists": {"field": "legal_citations"}},
                "size": 0,
                "aggs": {
                    "citation_counts": {
                        "script": {
                            "source": "params._source.legal_citations.size()",
                            "lang": "painless"
                        }
                    }
                }
            }
        )

        total_with_citations = docs_with_citations["hits"]["total"]["value"]
        print(f"Documents with legal_citations field: {total_with_citations}")

        # Get sample documents to analyze citation patterns
        sample_docs = await es.search(
            index="court-documents",
            body={
                "query": {"exists": {"field": "legal_citations"}},
                "size": 10,
                "_source": ["id", "case_name", "legal_citations"]
            }
        )

        print(f"\nSample citation analysis:")
        total_citations = 0
        unique_citations = set()

        for hit in sample_docs["hits"]["hits"]:
            doc = hit["_source"]
            citations = doc.get("legal_citations", [])
            doc_id = doc.get("id")
            case_name = doc.get("case_name", "Unknown")[:50]

            print(f"  Doc {doc_id} ({case_name}): {len(citations)} citations")
            total_citations += len(citations)

            for citation in citations:
                if isinstance(citation, dict):
                    cite_text = citation.get("citation", "")
                    if cite_text:
                        unique_citations.add(cite_text)
                elif isinstance(citation, str):
                    unique_citations.add(citation)

        print(f"\nCitation statistics from sample:")
        print(f"  Total citations: {total_citations}")
        print(f"  Unique citations: {len(unique_citations)}")
        print(f"  Citation reuse ratio: {total_citations / len(unique_citations) if unique_citations else 0:.2f}")

        # Step 2: Analyze why connectivity is so low
        print("\n2. CONNECTIVITY ANALYSIS")

        from legal_analytics.citation_analytics import CitationAnalyticsService

        citation_service = CitationAnalyticsService(es)
        network = await citation_service.build_citation_network()

        print(f"Citation network stats:")
        print(f"  Nodes: {network.network_statistics['total_nodes']}")
        print(f"  Edges: {network.network_statistics['total_edges']}")
        print(f"  Density: {network.network_statistics['density']:.6f}")
        print(f"  Document nodes: {network.network_statistics.get('document_nodes', 'unknown')}")
        print(f"  Citation nodes: {network.network_statistics.get('citation_nodes', 'unknown')}")

        # Step 3: Identify root causes
        print("\n3. ROOT CAUSE ANALYSIS")

        # Check if citations are creating document-to-document connections
        authority_rankings = network.authority_rankings
        document_authorities = {k: v for k, v in authority_rankings.items()
                               if k.isdigit()}  # Document IDs are numeric strings

        print(f"Documents with authority scores: {len(document_authorities)}")
        print(f"Top document authorities:")
        sorted_docs = sorted(document_authorities.items(),
                           key=lambda x: x[1], reverse=True)[:5]
        for doc_id, score in sorted_docs:
            print(f"  Doc {doc_id}: {score:.6f}")

        # Check citation overlap between documents
        print(f"\n4. CITATION OVERLAP ANALYSIS")

        # Get more documents for overlap analysis
        docs_for_overlap = await es.search(
            index="court-documents",
            body={
                "query": {"exists": {"field": "legal_citations"}},
                "size": 20,
                "_source": ["id", "legal_citations"]
            }
        )

        doc_citations = {}
        for hit in docs_for_overlap["hits"]["hits"]:
            doc = hit["_source"]
            doc_id = str(doc["id"])
            citations = doc.get("legal_citations", [])

            # Extract citation text
            citation_texts = []
            for citation in citations:
                if isinstance(citation, dict):
                    cite_text = citation.get("citation", "")
                    if cite_text:
                        citation_texts.append(cite_text)
                elif isinstance(citation, str):
                    citation_texts.append(citation)

            doc_citations[doc_id] = set(citation_texts)

        # Calculate pairwise overlaps
        overlap_count = 0
        total_pairs = 0
        overlap_details = []

        doc_ids = list(doc_citations.keys())
        for i, doc1 in enumerate(doc_ids):
            for doc2 in doc_ids[i+1:]:
                total_pairs += 1
                overlap = doc_citations[doc1].intersection(doc_citations[doc2])
                if overlap:
                    overlap_count += 1
                    overlap_details.append((doc1, doc2, len(overlap), list(overlap)[:3]))

        print(f"Citation overlap statistics:")
        print(f"  Document pairs analyzed: {total_pairs}")
        print(f"  Pairs with citation overlap: {overlap_count}")
        print(f"  Overlap percentage: {(overlap_count/total_pairs)*100:.1f}%")

        if overlap_details:
            print(f"  Top overlaps:")
            for doc1, doc2, count, samples in overlap_details[:5]:
                print(f"    Docs {doc1}-{doc2}: {count} shared citations ({samples})")

        # Step 5: Recommend solutions
        print(f"\n5. SOLUTION RECOMMENDATIONS")

        if overlap_count < total_pairs * 0.1:  # Less than 10% overlap
            print("❌ CRITICAL: Very low citation overlap between documents")
            print("Solutions:")
            print("  1. Enhanced co-citation analysis: Connect docs citing same sources")
            print("  2. Topic-based citation clustering: Group by legal topic + citation")
            print("  3. Temporal citation analysis: Connect cases from same time periods")
            print("  4. Judge-based citation patterns: Connect cases by same judge")

        if len(unique_citations) / total_citations > 0.8:  # Very few reused citations
            print("❌ CRITICAL: Citations rarely reused across documents")
            print("Solutions:")
            print("  1. Citation normalization: Standardize citation formats")
            print("  2. Fuzzy citation matching: Match similar but not identical citations")
            print("  3. Citation hierarchy: Connect related citations (e.g., different sections of same law)")

        total_documents = docs_for_overlap["hits"]["total"]["value"]
        if network.network_statistics['total_edges'] < total_documents * 0.1:
            print("❌ CRITICAL: Extremely sparse network (< 10% doc count)")
            print("Solutions:")
            print("  1. Multi-layer networks: Combine citation + topic + judicial similarity")
            print("  2. Semantic citation similarity: Connect conceptually similar citations")
            print("  3. Lower similarity thresholds: Accept weaker but valid connections")

    except Exception as e:
        print(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await es.close()

if __name__ == "__main__":
    asyncio.run(analyze_citation_sparsity())