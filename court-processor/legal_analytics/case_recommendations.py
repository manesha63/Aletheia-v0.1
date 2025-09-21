"""
Related Case Recommendation Service

Provides generalized legal case recommendations optimized for RAG consumption.
Uses citation networks, semantic similarity, and legal metadata for suggestions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import networkx as nx
import numpy as np
from functools import lru_cache
from pydantic import ValidationError

# Import validation models
from .validation import RecommendationRequest, validate_document_id, validate_confidence_score, validate_positive_integer

logger = logging.getLogger(__name__)

@dataclass
class CaseRecommendation:
    """Single case recommendation with scoring"""
    document_id: str
    similarity_score: float
    recommendation_reasons: List[str]
    citation_overlap: int
    topic_overlap: int
    judicial_similarity: float
    metadata: Dict[str, Any]

@dataclass
class RecommendationGraph:
    """Complete recommendation graph for RAG consumption"""
    target_document_id: str
    recommendations: List[CaseRecommendation]
    citation_network: Dict[str, List[str]]  # document_id -> [cited_cases]
    topic_clusters: Dict[str, List[str]]    # topic -> [document_ids]
    authority_scores: Dict[str, float]      # document_id -> authority_score
    total_candidates: int
    computation_metadata: Dict[str, Any]

class RelatedCaseService:
    """
    Generalized service for finding related legal cases using multiple signals:
    - Citation network connectivity
    - Legal topic similarity
    - Judicial pattern matching
    - Semantic embedding similarity
    - Case metadata alignment
    """

    def __init__(self, es_client):
        self.es = es_client
        self.index_name = "court-documents"
        self.citation_graph = nx.DiGraph()
        self.topic_graph = nx.Graph()
        self.authority_cache = {}
        self._graph_built = False

    async def build_recommendation_graphs(self, force_rebuild: bool = False) -> None:
        """Build citation and topic graphs from all documents using memory-efficient batch processing"""
        if self._graph_built and not force_rebuild:
            return

        logger.info("Building recommendation graphs from Elasticsearch using batch processing...")

        # Clear existing graphs
        self.citation_graph.clear()
        self.topic_graph.clear()

        # Process documents in batches to avoid memory exhaustion
        async def process_batch(documents):
            # Build citation network incrementally
            self._build_citation_graph_batch(documents)
            # Build topic co-occurrence graph incrementally
            self._build_topic_graph_batch(documents)

        await self._process_documents_in_batches(process_batch, batch_size=100)

        # Compute authority scores after all batches processed
        self._compute_authority_scores()

        self._graph_built = True
        logger.info(f"Graphs built in batches: {self.citation_graph.number_of_nodes()} citation nodes, "
                   f"{self.topic_graph.number_of_nodes()} topic nodes")

    async def get_related_cases(
        self,
        document_id: str,
        max_recommendations: int = 20,
        min_score_threshold: float = 0.1,
        include_full_graph: bool = True
    ) -> RecommendationGraph:
        """
        Get related cases optimized for RAG consumption

        Returns complete relational data including:
        - Ranked recommendations with detailed scoring
        - Citation network subgraph
        - Topic cluster memberships
        - Authority rankings
        - Computational metadata for LLM reasoning
        """

        # Validate inputs using Pydantic
        try:
            request = RecommendationRequest(
                document_id=document_id,
                max_recommendations=max_recommendations,
                min_confidence=min_score_threshold,  # Use min_confidence parameter name
                include_full_graph=include_full_graph
            )
        except ValidationError as e:
            logger.error(f"Invalid recommendation request: {e}")
            raise ValueError(f"Invalid input parameters: {e}")

        # Use validated values
        document_id = request.document_id
        max_recommendations = request.max_recommendations
        min_score_threshold = request.min_confidence  # Map back to local variable name
        include_full_graph = request.include_full_graph

        await self.build_recommendation_graphs()

        # Get source document
        source_doc = await self._get_document(document_id)
        if not source_doc:
            raise ValueError(f"Document {document_id} not found")

        # Calculate recommendations using multiple signals
        candidates = await self._find_candidate_documents(source_doc, max_recommendations * 3)

        recommendations = []
        for candidate in candidates:
            score, reasons = self._calculate_similarity_score(source_doc, candidate)

            if score >= min_score_threshold:
                recommendations.append(CaseRecommendation(
                    document_id=str(candidate["id"]),
                    similarity_score=score,
                    recommendation_reasons=reasons,
                    citation_overlap=self._count_citation_overlap(source_doc, candidate),
                    topic_overlap=self._count_topic_overlap(source_doc, candidate),
                    judicial_similarity=self._calculate_judicial_similarity(source_doc, candidate),
                    metadata=self._extract_case_metadata(candidate)
                ))

        # Sort by score and limit
        recommendations.sort(key=lambda x: x.similarity_score, reverse=True)
        recommendations = recommendations[:max_recommendations]

        # Build recommendation graph
        return RecommendationGraph(
            target_document_id=document_id,
            recommendations=recommendations,
            citation_network=self._build_citation_subgraph(source_doc, recommendations) if include_full_graph else {},
            topic_clusters=self._build_topic_clusters(source_doc, recommendations) if include_full_graph else {},
            authority_scores=self._get_authority_scores([r.document_id for r in recommendations]),
            total_candidates=len(candidates),
            computation_metadata={
                "algorithm_version": "1.0",
                "signals_used": ["citations", "topics", "judicial", "semantic", "metadata"],
                "graph_stats": {
                    "citation_nodes": self.citation_graph.number_of_nodes(),
                    "citation_edges": self.citation_graph.number_of_edges(),
                    "topic_nodes": self.topic_graph.number_of_nodes(),
                    "topic_edges": self.topic_graph.number_of_edges()
                }
            }
        )

    async def _process_documents_in_batches(self, batch_processor, batch_size: int = 100) -> None:
        """Process documents in memory-efficient batches"""
        query = {
            "query": {"match_all": {}},
            "size": batch_size,
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_citations", "legal_topics", "case_dispositions",
                "content_embedding", "document_type", "content_length"
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

        logger.info(f"Processed {total_processed} documents in batches")

    async def _fetch_all_documents(self, batch_size: int = 1000) -> List[Dict]:
        """Fetch all documents with citation and topic data - DEPRECATED: Use _process_documents_in_batches"""
        logger.warning("_fetch_all_documents is deprecated. Use _process_documents_in_batches for better memory efficiency")

        documents = []

        async def collect_batch(batch):
            documents.extend(batch)

        await self._process_documents_in_batches(collect_batch, batch_size)
        return documents

    def _build_citation_graph(self, documents: List[Dict]) -> None:
        """Build citation network graph"""
        self.citation_graph.clear()

        for doc in documents:
            doc_id = str(doc.get("id"))
            self.citation_graph.add_node(doc_id, **{
                "case_name": doc.get("case_name"),
                "judge": doc.get("judge_name"),
                "court": doc.get("court_id"),
                "type": "document"
            })

            # Add citation edges
            citations = doc.get("legal_citations", []) or []
            for citation in citations:
                if isinstance(citation, dict):
                    cite_text = citation.get("citation", "")
                    if cite_text:
                        # Add citation as node
                        if not self.citation_graph.has_node(cite_text):
                            self.citation_graph.add_node(cite_text, type="citation")

                        # Add edge
                        self.citation_graph.add_edge(doc_id, cite_text, **{
                            "type": "cites",
                            "confidence": citation.get("confidence", 1.0)
                        })

    def _build_topic_graph(self, documents: List[Dict]) -> None:
        """Build topic co-occurrence graph"""
        self.topic_graph.clear()
        topic_cooccurrence = defaultdict(lambda: defaultdict(int))

        for doc in documents:
            topics = doc.get("legal_topics", []) or []
            valid_topics = []

            for topic in topics:
                if isinstance(topic, dict):
                    topic_name = topic.get("topic")
                    confidence = topic.get("confidence", 0.0)
                    if topic_name and confidence >= 0.5:
                        valid_topics.append(topic_name)

            # Create topic co-occurrence
            for i, topic1 in enumerate(valid_topics):
                self.topic_graph.add_node(topic1)
                for topic2 in valid_topics[i+1:]:
                    self.topic_graph.add_node(topic2)
                    topic_cooccurrence[topic1][topic2] += 1
                    topic_cooccurrence[topic2][topic1] += 1

        # Add edges with weights
        for topic1, connections in topic_cooccurrence.items():
            for topic2, weight in connections.items():
                if weight >= 2:  # Minimum co-occurrence threshold
                    self.topic_graph.add_edge(topic1, topic2, weight=weight)

    def _build_citation_graph_batch(self, documents: List[Dict]) -> None:
        """Build citation network graph incrementally from a batch of documents"""
        for doc in documents:
            doc_id = str(doc.get("id"))
            self.citation_graph.add_node(doc_id, **{
                "case_name": doc.get("case_name"),
                "judge": doc.get("judge_name"),
                "court": doc.get("court_id"),
                "type": "document"
            })

            # Add citation edges
            citations = doc.get("legal_citations", []) or []
            for citation in citations:
                if isinstance(citation, dict):
                    cite_text = citation.get("citation", "")
                    if cite_text:
                        # Add citation as node
                        if not self.citation_graph.has_node(cite_text):
                            self.citation_graph.add_node(cite_text, type="citation")

                        # Add edge
                        self.citation_graph.add_edge(doc_id, cite_text, **{
                            "type": "cites",
                            "confidence": citation.get("confidence", 1.0)
                        })

    def _build_topic_graph_batch(self, documents: List[Dict]) -> None:
        """Build topic co-occurrence graph incrementally from a batch of documents"""
        topic_cooccurrence = defaultdict(lambda: defaultdict(int))

        for doc in documents:
            topics = doc.get("legal_topics", []) or []
            valid_topics = []

            for topic in topics:
                if isinstance(topic, dict):
                    topic_name = topic.get("topic")
                    confidence = topic.get("confidence", 0.0)
                    if topic_name and confidence >= 0.5:
                        valid_topics.append(topic_name)

            # Create topic co-occurrence within this document
            for i, topic1 in enumerate(valid_topics):
                self.topic_graph.add_node(topic1)
                for topic2 in valid_topics[i+1:]:
                    self.topic_graph.add_node(topic2)
                    topic_cooccurrence[topic1][topic2] += 1
                    topic_cooccurrence[topic2][topic1] += 1

        # Add/update edges with weights
        for topic1, connections in topic_cooccurrence.items():
            for topic2, weight in connections.items():
                if weight >= 1:  # Lower threshold for batch processing
                    # If edge exists, update weight; otherwise create new edge
                    if self.topic_graph.has_edge(topic1, topic2):
                        current_weight = self.topic_graph[topic1][topic2].get('weight', 0)
                        self.topic_graph[topic1][topic2]['weight'] = current_weight + weight
                    else:
                        self.topic_graph.add_edge(topic1, topic2, weight=weight)

    def _compute_authority_scores(self) -> None:
        """Compute citation authority scores using PageRank"""
        try:
            # Create subgraph of only document nodes
            doc_nodes = [n for n, d in self.citation_graph.nodes(data=True)
                        if d.get("type") == "document"]
            doc_graph = self.citation_graph.subgraph(doc_nodes)

            if doc_graph.number_of_nodes() > 0:
                self.authority_cache = nx.pagerank(doc_graph, weight="confidence")
            else:
                self.authority_cache = {}

        except Exception as e:
            logger.warning(f"Failed to compute authority scores: {e}")
            self.authority_cache = {}

    async def _find_candidate_documents(self, source_doc: Dict, max_candidates: int) -> List[Dict]:
        """Find candidate documents using multiple search strategies"""
        candidates = []
        source_id = str(source_doc["id"])

        # Strategy 1: Citation-connected documents
        citation_candidates = self._find_citation_connected(source_id)

        # Strategy 2: Topic-similar documents
        topic_candidates = await self._find_topic_similar(source_doc)

        # Strategy 3: Court/judge similar documents
        judicial_candidates = await self._find_judicial_similar(source_doc)

        # Strategy 4: Semantic similarity (if embeddings available)
        semantic_candidates = await self._find_semantic_similar(source_doc)

        # Combine and deduplicate
        all_candidates = set()
        for candidate_list in [citation_candidates, topic_candidates, judicial_candidates, semantic_candidates]:
            all_candidates.update(candidate_list)

        # Remove source document
        all_candidates.discard(source_id)

        # Fetch candidate documents
        if all_candidates:
            candidates = await self._fetch_documents_by_ids(list(all_candidates)[:max_candidates])

        return candidates

    def _find_citation_connected(self, document_id: str) -> List[str]:
        """Find documents connected via citation network"""
        connected = set()

        if document_id in self.citation_graph:
            # Documents that cite the same sources
            for cited_source in self.citation_graph.neighbors(document_id):
                # Find other documents that cite this source
                citing_docs = [pred for pred in self.citation_graph.predecessors(cited_source)
                              if self.citation_graph.nodes[pred].get("type") == "document"]
                connected.update(citing_docs)

        return list(connected)

    async def _find_topic_similar(self, source_doc: Dict, limit: int = 50) -> List[str]:
        """Find documents with similar legal topics"""
        source_topics = []
        topics = source_doc.get("legal_topics", []) or []

        for topic in topics:
            if isinstance(topic, dict) and topic.get("confidence", 0) >= 0.5:
                source_topics.append(topic.get("topic"))

        if not source_topics:
            return []

        # Search for documents with overlapping topics
        query = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"legal_topics.topic.keyword": topic}}
                        for topic in source_topics
                    ]
                }
            },
            "size": limit,
            "_source": ["id"]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            return [str(hit["_source"]["id"]) for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"Topic search failed: {e}")
            return []

    async def _find_judicial_similar(self, source_doc: Dict, limit: int = 30) -> List[str]:
        """Find documents from same judge/court"""
        filters = []

        if source_doc.get("judge_name"):
            filters.append({"term": {"judge_name.keyword": source_doc["judge_name"]}})

        if source_doc.get("court_id"):
            filters.append({"term": {"court_id.keyword": source_doc["court_id"]}})

        if not filters:
            return []

        query = {
            "query": {"bool": {"should": filters}},
            "size": limit,
            "_source": ["id"]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            return [str(hit["_source"]["id"]) for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"Judicial search failed: {e}")
            return []

    async def _find_semantic_similar(self, source_doc: Dict, limit: int = 30) -> List[str]:
        """Find semantically similar documents using embeddings"""
        if not source_doc.get("content_embedding"):
            return []

        query = {
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": """
                            if (doc['content_embedding'].size() == 0) return 0.0;
                            return cosineSimilarity(params.query_vector, 'content_embedding');
                        """,
                        "params": {"query_vector": source_doc["content_embedding"]}
                    }
                }
            },
            "size": limit,
            "_source": ["id"]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            return [str(hit["_source"]["id"]) for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")
            return []

    async def _fetch_documents_by_ids(self, doc_ids: List[str]) -> List[Dict]:
        """Fetch multiple documents by ID"""
        if not doc_ids:
            return []

        query = {
            "query": {"terms": {"id": doc_ids}},
            "size": len(doc_ids),
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_citations", "legal_topics", "case_dispositions",
                "content_embedding", "document_type", "content_length"
            ]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Failed to fetch documents: {e}")
            return []

    async def _get_document(self, document_id: str) -> Optional[Dict]:
        """Get single document by ID"""
        docs = await self._fetch_documents_by_ids([document_id])
        return docs[0] if docs else None

    def _calculate_similarity_score(self, source_doc: Dict, candidate_doc: Dict) -> Tuple[float, List[str]]:
        """Calculate multi-factor similarity score"""
        reasons = []
        scores = []

        # Citation overlap score
        citation_score = self._count_citation_overlap(source_doc, candidate_doc) * 0.3
        if citation_score > 0:
            scores.append(citation_score)
            reasons.append(f"citation_overlap:{citation_score:.2f}")

        # Topic overlap score
        topic_score = self._count_topic_overlap(source_doc, candidate_doc) * 0.25
        if topic_score > 0:
            scores.append(topic_score)
            reasons.append(f"topic_overlap:{topic_score:.2f}")

        # Judicial similarity score
        judicial_score = self._calculate_judicial_similarity(source_doc, candidate_doc) * 0.2
        if judicial_score > 0:
            scores.append(judicial_score)
            reasons.append(f"judicial_similarity:{judicial_score:.2f}")

        # Authority boost
        authority_score = self.authority_cache.get(str(candidate_doc["id"]), 0) * 0.15
        if authority_score > 0:
            scores.append(authority_score)
            reasons.append(f"authority:{authority_score:.2f}")

        # Semantic similarity (if available)
        semantic_score = self._calculate_semantic_similarity(source_doc, candidate_doc) * 0.1
        if semantic_score > 0:
            scores.append(semantic_score)
            reasons.append(f"semantic:{semantic_score:.2f}")

        total_score = sum(scores) if scores else 0.0
        return total_score, reasons

    def _count_citation_overlap(self, doc1: Dict, doc2: Dict) -> int:
        """Count overlapping citations between documents"""
        citations1 = set()
        citations2 = set()

        for citations, target_set in [(doc1.get("legal_citations", []), citations1),
                                     (doc2.get("legal_citations", []), citations2)]:
            if citations:
                for citation in citations:
                    if isinstance(citation, dict):
                        cite_text = citation.get("citation")
                        if cite_text:
                            target_set.add(cite_text)

        return len(citations1.intersection(citations2))

    def _count_topic_overlap(self, doc1: Dict, doc2: Dict) -> int:
        """Count overlapping legal topics between documents"""
        topics1 = set()
        topics2 = set()

        for doc, target_set in [(doc1, topics1), (doc2, topics2)]:
            topics = doc.get("legal_topics", []) or []
            for topic in topics:
                if isinstance(topic, dict) and topic.get("confidence", 0) >= 0.5:
                    target_set.add(topic.get("topic"))

        return len(topics1.intersection(topics2))

    def _calculate_judicial_similarity(self, doc1: Dict, doc2: Dict) -> float:
        """Calculate judicial similarity (same judge/court)"""
        score = 0.0

        if doc1.get("judge_name") and doc1["judge_name"] == doc2.get("judge_name"):
            score += 0.6

        if doc1.get("court_id") and doc1["court_id"] == doc2.get("court_id"):
            score += 0.4

        return min(score, 1.0)

    def _calculate_semantic_similarity(self, doc1: Dict, doc2: Dict) -> float:
        """Calculate semantic similarity using embeddings"""
        emb1 = doc1.get("content_embedding")
        emb2 = doc2.get("content_embedding")

        if not emb1 or not emb2:
            return 0.0

        try:
            # Cosine similarity
            emb1 = np.array(emb1)
            emb2 = np.array(emb2)
            similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            return max(0.0, similarity)  # Ensure non-negative
        except Exception:
            return 0.0

    def _extract_case_metadata(self, doc: Dict) -> Dict[str, Any]:
        """Extract case metadata for RAG consumption"""
        return {
            "case_name": doc.get("case_name"),
            "judge_name": doc.get("judge_name"),
            "court_id": doc.get("court_id"),
            "filing_date": doc.get("filing_date"),
            "document_type": doc.get("document_type"),
            "content_length": doc.get("content_length", 0),
            "citation_count": len(doc.get("legal_citations", []) or []),
            "topic_count": len(doc.get("legal_topics", []) or [])
        }

    def _build_citation_subgraph(self, source_doc: Dict, recommendations: List[CaseRecommendation]) -> Dict[str, List[str]]:
        """Build citation network subgraph for recommendations"""
        doc_ids = {str(source_doc["id"])} | {r.document_id for r in recommendations}
        subgraph = {}

        for doc_id in doc_ids:
            if doc_id in self.citation_graph:
                cited = [neighbor for neighbor in self.citation_graph.neighbors(doc_id)
                        if self.citation_graph.nodes[neighbor].get("type") == "citation"]
                subgraph[doc_id] = cited

        return subgraph

    def _build_topic_clusters(self, source_doc: Dict, recommendations: List[CaseRecommendation]) -> Dict[str, List[str]]:
        """Build topic clusters for recommendations"""
        clusters = defaultdict(list)
        doc_ids = {str(source_doc["id"])} | {r.document_id for r in recommendations}

        # Add source document topics
        self._add_doc_to_clusters(source_doc, str(source_doc["id"]), clusters)

        # Add recommendation topics
        for rec in recommendations:
            if hasattr(rec, 'metadata') and rec.metadata:
                # Would need to fetch full doc data here if needed
                pass

        return dict(clusters)

    def _add_doc_to_clusters(self, doc: Dict, doc_id: str, clusters: Dict) -> None:
        """Add document to topic clusters"""
        topics = doc.get("legal_topics", []) or []
        for topic in topics:
            if isinstance(topic, dict) and topic.get("confidence", 0) >= 0.5:
                topic_name = topic.get("topic")
                if topic_name:
                    clusters[topic_name].append(doc_id)

    def _get_authority_scores(self, doc_ids: List[str]) -> Dict[str, float]:
        """Get authority scores for document IDs"""
        return {doc_id: self.authority_cache.get(doc_id, 0.0) for doc_id in doc_ids}

    async def get_network_statistics(self) -> Dict[str, Any]:
        """Get network statistics for monitoring and debugging"""
        await self.build_recommendation_graphs()

        return {
            "citation_network": {
                "nodes": self.citation_graph.number_of_nodes(),
                "edges": self.citation_graph.number_of_edges(),
                "document_nodes": len([n for n, d in self.citation_graph.nodes(data=True)
                                     if d.get("type") == "document"]),
                "citation_nodes": len([n for n, d in self.citation_graph.nodes(data=True)
                                     if d.get("type") == "citation"])
            },
            "topic_network": {
                "nodes": self.topic_graph.number_of_nodes(),
                "edges": self.topic_graph.number_of_edges()
            },
            "authority_scores": {
                "computed": len(self.authority_cache),
                "top_authorities": sorted(self.authority_cache.items(),
                                        key=lambda x: x[1], reverse=True)[:10]
            }
        }