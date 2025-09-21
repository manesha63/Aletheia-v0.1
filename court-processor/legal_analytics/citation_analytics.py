"""
Citation Analytics Service

Provides generalized citation network analysis optimized for RAG consumption.
Includes authority ranking, citation patterns, and influence scoring.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import networkx as nx
import numpy as np
from pydantic import ValidationError

# Import validation models
from .validation import CitationAnalysisRequest, validate_document_id

logger = logging.getLogger(__name__)

@dataclass
class CitationAuthority:
    """Citation authority information for a document or case"""
    entity_id: str
    entity_type: str  # "document", "case", "statute", "regulation"
    authority_score: float
    citation_count: int
    citing_documents: List[str]
    authority_rank: int
    metadata: Dict[str, Any]

@dataclass
class CitationNetwork:
    """Complete citation network analysis for RAG consumption"""
    authorities: List[CitationAuthority]
    citation_graph: Dict[str, List[str]]  # entity_id -> [cited_entities]
    reverse_citation_graph: Dict[str, List[str]]  # entity_id -> [citing_entities]
    authority_rankings: Dict[str, float]  # entity_id -> authority_score
    citation_patterns: Dict[str, Any]  # Legal citation patterns analysis
    network_statistics: Dict[str, Any]  # Graph metrics
    computation_metadata: Dict[str, Any]

class CitationAnalyticsService:
    """
    Generalized service for legal citation analysis using:
    - Citation authority ranking (PageRank-based)
    - Citation pattern analysis
    - Legal precedent identification
    - Cross-citation network analysis
    """

    def __init__(self, es_client):
        self.es = es_client
        self.index_name = "court-documents"
        self.citation_graph = nx.DiGraph()
        self.authority_scores = {}
        self._graph_built = False

    async def build_citation_network(self, force_rebuild: bool = False) -> CitationNetwork:
        """
        Build complete citation network optimized for RAG consumption

        Returns comprehensive citation analysis including:
        - Authority rankings for all cited entities
        - Citation relationship graphs
        - Legal citation patterns
        - Network statistics and metadata
        """

        if not self._graph_built or force_rebuild:
            await self._build_graph()

        # Calculate authority scores
        self._calculate_authority_scores()

        # Build authorities list
        authorities = self._build_authorities_list()

        # Extract citation graphs
        citation_graph, reverse_citation_graph = self._extract_citation_graphs()

        # Analyze citation patterns
        citation_patterns = await self._analyze_citation_patterns()

        # Calculate network statistics
        network_statistics = self._calculate_network_statistics()

        return CitationNetwork(
            authorities=authorities,
            citation_graph=citation_graph,
            reverse_citation_graph=reverse_citation_graph,
            authority_rankings=self.authority_scores.copy(),
            citation_patterns=citation_patterns,
            network_statistics=network_statistics,
            computation_metadata={
                "algorithm_version": "1.0",
                "authority_algorithm": "pagerank",
                "total_nodes": self.citation_graph.number_of_nodes(),
                "total_edges": self.citation_graph.number_of_edges(),
                "graph_density": nx.density(self.citation_graph),
                "parameters": {
                    "pagerank_damping": 0.85,
                    "min_citation_confidence": 0.3
                }
            }
        )

    async def get_document_citation_analysis(self, document_id: str) -> Dict[str, Any]:
        """Get detailed citation analysis for a specific document"""

        # Validate input
        try:
            validated_id = validate_document_id(document_id)
        except ValueError as e:
            logger.error(f"Invalid document ID: {e}")
            raise ValueError(f"Invalid document ID: {e}")

        if not self._graph_built:
            await self._build_graph()

        # Use validated document ID
        document_id = validated_id
        doc = await self._get_document(document_id)
        if not doc:
            return {}

        # Citations made by this document
        outgoing_citations = list(self.citation_graph.neighbors(document_id)) if document_id in self.citation_graph else []

        # Documents that cite this document
        incoming_citations = list(self.citation_graph.predecessors(document_id)) if document_id in self.citation_graph else []

        # Authority score
        authority_score = self.authority_scores.get(document_id, 0.0)

        # Citation patterns
        citation_analysis = self._analyze_document_citations(doc)

        return {
            "document_id": document_id,
            "authority_score": authority_score,
            "outgoing_citations": {
                "count": len(outgoing_citations),
                "entities": outgoing_citations
            },
            "incoming_citations": {
                "count": len(incoming_citations),
                "entities": incoming_citations
            },
            "citation_analysis": citation_analysis,
            "network_position": {
                "in_degree": self.citation_graph.in_degree(document_id) if document_id in self.citation_graph else 0,
                "out_degree": self.citation_graph.out_degree(document_id) if document_id in self.citation_graph else 0
            }
        }

    async def _build_graph(self) -> None:
        """Build citation network graph from all documents"""
        logger.info("Building citation network from Elasticsearch...")

        documents = await self._fetch_all_documents()

        self.citation_graph.clear()

        for doc in documents:
            doc_id = str(doc.get("id"))

            # Add document node
            self.citation_graph.add_node(doc_id, **{
                "type": "document",
                "case_name": doc.get("case_name"),
                "judge": doc.get("judge_name"),
                "court": doc.get("court_id"),
                "filing_date": doc.get("filing_date")
            })

            # Add citation edges
            citations = doc.get("legal_citations", []) or []
            for citation in citations:
                if isinstance(citation, dict):
                    cite_text = citation.get("citation", "")
                    cite_type = citation.get("type", "unknown")
                    confidence = citation.get("confidence", 1.0)

                    if cite_text and confidence >= 0.3:  # Minimum confidence threshold
                        # Normalize citation text
                        normalized_cite = self._normalize_citation(cite_text, cite_type)

                        # Add citation node if not exists
                        if not self.citation_graph.has_node(normalized_cite):
                            self.citation_graph.add_node(normalized_cite, **{
                                "type": "citation",
                                "citation_type": cite_type,
                                "original_text": cite_text
                            })

                        # Add edge
                        self.citation_graph.add_edge(doc_id, normalized_cite, **{
                            "confidence": confidence,
                            "citation_type": cite_type
                        })

        self._graph_built = True
        logger.info(f"Citation graph built: {self.citation_graph.number_of_nodes()} nodes, "
                   f"{self.citation_graph.number_of_edges()} edges")

    def _normalize_citation(self, citation_text: str, citation_type: str) -> str:
        """Normalize citation text for consistent referencing"""
        # Basic normalization - could be enhanced with more sophisticated parsing
        normalized = citation_text.strip()

        # Remove common variations
        normalized = normalized.replace("  ", " ")

        # Type-specific normalization
        if citation_type == "federal_reporter":
            # Standardize federal reporter citations
            import re
            pattern = r"(\d+)\s*F\.\s*(\d+d?)\s*(\d+)"
            match = re.search(pattern, normalized)
            if match:
                volume, series, page = match.groups()
                normalized = f"{volume} F.{series} {page}"

        elif citation_type == "usc":
            # Standardize USC citations
            import re
            pattern = r"(\d+)\s*U\.?S\.?C\.?\s*§?\s*(\d+)"
            match = re.search(pattern, normalized)
            if match:
                title, section = match.groups()
                normalized = f"{title} U.S.C. § {section}"

        return normalized

    def _calculate_authority_scores(self) -> None:
        """Calculate authority scores using PageRank algorithm"""
        try:
            if self.citation_graph.number_of_nodes() > 0:
                # Use edge weights (confidence) in PageRank calculation
                self.authority_scores = nx.pagerank(
                    self.citation_graph,
                    weight="confidence",
                    alpha=0.85  # Damping factor
                )
            else:
                self.authority_scores = {}

            logger.info(f"Calculated authority scores for {len(self.authority_scores)} entities")

        except Exception as e:
            logger.error(f"Failed to calculate authority scores: {e}")
            self.authority_scores = {}

    def _build_authorities_list(self) -> List[CitationAuthority]:
        """Build ranked list of citation authorities"""
        authorities = []

        # Sort by authority score
        sorted_entities = sorted(
            self.authority_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for rank, (entity_id, score) in enumerate(sorted_entities, 1):
            node_data = self.citation_graph.nodes[entity_id]
            entity_type = node_data.get("type", "unknown")

            # Count citations
            citing_documents = list(self.citation_graph.predecessors(entity_id))
            citation_count = len(citing_documents)

            # Extract metadata
            if entity_type == "document":
                metadata = {
                    "case_name": node_data.get("case_name"),
                    "judge": node_data.get("judge"),
                    "court": node_data.get("court"),
                    "filing_date": node_data.get("filing_date")
                }
            else:  # citation
                metadata = {
                    "citation_type": node_data.get("citation_type"),
                    "original_text": node_data.get("original_text")
                }

            authorities.append(CitationAuthority(
                entity_id=entity_id,
                entity_type=entity_type,
                authority_score=score,
                citation_count=citation_count,
                citing_documents=citing_documents,
                authority_rank=rank,
                metadata=metadata
            ))

        return authorities

    def _extract_citation_graphs(self) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        """Extract citation graphs for RAG consumption"""
        citation_graph = {}
        reverse_citation_graph = {}

        for node in self.citation_graph.nodes():
            # Forward citations (what this entity cites)
            cited_entities = list(self.citation_graph.neighbors(node))
            citation_graph[node] = cited_entities

            # Reverse citations (what cites this entity)
            citing_entities = list(self.citation_graph.predecessors(node))
            reverse_citation_graph[node] = citing_entities

        return citation_graph, reverse_citation_graph

    async def _analyze_citation_patterns(self) -> Dict[str, Any]:
        """Analyze legal citation patterns across the corpus"""
        patterns = {
            "citation_types": self._analyze_citation_types(),
            "temporal_patterns": await self._analyze_temporal_patterns(),
            "judicial_patterns": self._analyze_judicial_patterns(),
            "authority_distribution": self._analyze_authority_distribution()
        }

        return patterns

    def _analyze_citation_types(self) -> Dict[str, Any]:
        """Analyze distribution of citation types"""
        type_counts = Counter()
        total_citations = 0

        for node, data in self.citation_graph.nodes(data=True):
            if data.get("type") == "citation":
                cite_type = data.get("citation_type", "unknown")
                # Count incoming citations (how often this citation is used)
                citation_frequency = self.citation_graph.in_degree(node)
                type_counts[cite_type] += citation_frequency
                total_citations += citation_frequency

        return {
            "type_distribution": dict(type_counts),
            "total_citations": total_citations,
            "unique_citation_types": len(type_counts),
            "most_common_types": type_counts.most_common(10)
        }

    async def _analyze_temporal_patterns(self) -> Dict[str, Any]:
        """Analyze citation patterns over time"""
        # This would require date parsing and temporal analysis
        # For now, return basic structure
        return {
            "citation_trends": {},
            "temporal_authority_changes": {},
            "note": "Temporal analysis requires document date parsing"
        }

    def _analyze_judicial_patterns(self) -> Dict[str, Any]:
        """Analyze citation patterns by judge and court"""
        judge_patterns = defaultdict(lambda: {"citations_made": 0, "authority_score": 0.0})
        court_patterns = defaultdict(lambda: {"citations_made": 0, "authority_score": 0.0})

        for node, data in self.citation_graph.nodes(data=True):
            if data.get("type") == "document":
                judge = data.get("judge")
                court = data.get("court")
                authority = self.authority_scores.get(node, 0.0)
                citations_made = self.citation_graph.out_degree(node)

                if judge:
                    judge_patterns[judge]["citations_made"] += citations_made
                    judge_patterns[judge]["authority_score"] += authority

                if court:
                    court_patterns[court]["citations_made"] += citations_made
                    court_patterns[court]["authority_score"] += authority

        return {
            "judge_patterns": dict(judge_patterns),
            "court_patterns": dict(court_patterns),
            "top_citing_judges": sorted(
                judge_patterns.items(),
                key=lambda x: x[1]["citations_made"],
                reverse=True
            )[:10],
            "most_authoritative_courts": sorted(
                court_patterns.items(),
                key=lambda x: x[1]["authority_score"],
                reverse=True
            )[:10]
        }

    def _analyze_authority_distribution(self) -> Dict[str, Any]:
        """Analyze distribution of authority scores"""
        if not self.authority_scores:
            return {}

        scores = list(self.authority_scores.values())
        scores_array = np.array(scores)

        return {
            "total_entities": len(scores),
            "mean_authority": float(np.mean(scores_array)),
            "median_authority": float(np.median(scores_array)),
            "std_authority": float(np.std(scores_array)),
            "min_authority": float(np.min(scores_array)),
            "max_authority": float(np.max(scores_array)),
            "authority_percentiles": {
                "95th": float(np.percentile(scores_array, 95)),
                "90th": float(np.percentile(scores_array, 90)),
                "75th": float(np.percentile(scores_array, 75)),
                "50th": float(np.percentile(scores_array, 50)),
                "25th": float(np.percentile(scores_array, 25))
            }
        }

    def _calculate_network_statistics(self) -> Dict[str, Any]:
        """Calculate network-level statistics"""
        if self.citation_graph.number_of_nodes() == 0:
            return {}

        stats = {
            "basic_metrics": {
                "nodes": self.citation_graph.number_of_nodes(),
                "edges": self.citation_graph.number_of_edges(),
                "density": nx.density(self.citation_graph),
                "is_connected": nx.is_weakly_connected(self.citation_graph)
            }
        }

        # Document vs citation nodes
        doc_nodes = sum(1 for _, data in self.citation_graph.nodes(data=True)
                       if data.get("type") == "document")
        citation_nodes = self.citation_graph.number_of_nodes() - doc_nodes

        stats["node_types"] = {
            "documents": doc_nodes,
            "citations": citation_nodes
        }

        # Degree statistics
        in_degrees = [d for n, d in self.citation_graph.in_degree()]
        out_degrees = [d for n, d in self.citation_graph.out_degree()]

        if in_degrees:
            stats["degree_statistics"] = {
                "in_degree": {
                    "mean": np.mean(in_degrees),
                    "max": max(in_degrees),
                    "min": min(in_degrees)
                },
                "out_degree": {
                    "mean": np.mean(out_degrees),
                    "max": max(out_degrees),
                    "min": min(out_degrees)
                }
            }

        return stats

    def _analyze_document_citations(self, doc: Dict) -> Dict[str, Any]:
        """Analyze citations for a specific document"""
        citations = doc.get("legal_citations", []) or []

        analysis = {
            "total_citations": len(citations),
            "citation_types": Counter(),
            "confidence_distribution": [],
            "high_confidence_citations": []
        }

        for citation in citations:
            if isinstance(citation, dict):
                cite_type = citation.get("type", "unknown")
                confidence = citation.get("confidence", 1.0)
                cite_text = citation.get("citation", "")

                analysis["citation_types"][cite_type] += 1
                analysis["confidence_distribution"].append(confidence)

                if confidence >= 0.8:  # High confidence threshold
                    analysis["high_confidence_citations"].append({
                        "citation": cite_text,
                        "type": cite_type,
                        "confidence": confidence
                    })

        # Calculate average confidence
        if analysis["confidence_distribution"]:
            analysis["average_confidence"] = np.mean(analysis["confidence_distribution"])
        else:
            analysis["average_confidence"] = 0.0

        analysis["citation_types"] = dict(analysis["citation_types"])

        return analysis

    async def _process_documents_in_batches(self, batch_processor, batch_size: int = 100) -> None:
        """Process documents in memory-efficient batches"""
        query = {
            "query": {"match_all": {}},
            "size": batch_size,
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_citations", "document_type"
            ]
        }

        # Use scroll API for large datasets
        response = await self.es.search(
            index=self.index_name,
            body=query,
            scroll="5m"
        )

        scroll_id = response["_scroll_id"]
        hits = response["hits"]["hits"]
        total_processed = 0

        try:
            while hits:
                # Process current batch
                batch_documents = [hit["_source"] for hit in hits]
                await batch_processor(batch_documents)
                total_processed += len(batch_documents)

                # Fetch next batch
                response = await self.es.scroll(
                    scroll_id=scroll_id,
                    scroll="5m"
                )
                hits = response["hits"]["hits"]

        finally:
            # Always clear scroll
            await self.es.clear_scroll(scroll_id=scroll_id)

        logger.info(f"Processed {total_processed} documents in batches for citation analysis")

    async def _fetch_all_documents(self, batch_size: int = 1000) -> List[Dict]:
        """Fetch all documents with citation data - DEPRECATED: Use _process_documents_in_batches"""
        logger.warning("_fetch_all_documents is deprecated. Use _process_documents_in_batches for better memory efficiency")

        documents = []

        async def collect_batch(batch):
            documents.extend(batch)

        await self._process_documents_in_batches(collect_batch, batch_size)
        return documents

    async def _get_document(self, document_id: str) -> Optional[Dict]:
        """Get single document by ID"""
        query = {
            "query": {"term": {"id": document_id}},
            "size": 1,
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_citations", "document_type"
            ]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            hits = response["hits"]["hits"]
            return hits[0]["_source"] if hits else None
        except Exception as e:
            logger.error(f"Failed to fetch document {document_id}: {e}")
            return None

    async def get_citation_statistics(self) -> Dict[str, Any]:
        """Get citation network statistics for monitoring"""
        if not self._graph_built:
            await self._build_graph()

        return {
            "network_built": self._graph_built,
            "authority_scores_computed": len(self.authority_scores),
            "graph_metrics": self._calculate_network_statistics()
        }