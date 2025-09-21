"""
Topic Clustering Service

Provides generalized legal topic clustering optimized for RAG consumption.
Uses hierarchical clustering, topic co-occurrence, and semantic embeddings.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import networkx as nx
import numpy as np
from sklearn.cluster import AgglomerativeClustering, DBSCAN
from pydantic import ValidationError

# Import validation models
from .validation import TopicClusteringRequest, validate_positive_integer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler
import json

logger = logging.getLogger(__name__)

@dataclass
class TopicCluster:
    """Single topic cluster with metadata"""
    cluster_id: str
    topic_names: List[str]
    document_ids: List[str]
    cluster_center: Optional[List[float]]
    coherence_score: float
    size: int
    representative_cases: List[Dict[str, Any]]

@dataclass
class ClusterGraph:
    """Complete topic clustering results for RAG consumption"""
    clusters: List[TopicCluster]
    topic_hierarchy: Dict[str, List[str]]  # parent_topic -> [child_topics]
    document_cluster_mapping: Dict[str, str]  # document_id -> cluster_id
    topic_similarity_matrix: Dict[str, Dict[str, float]]  # topic -> {topic: similarity}
    cluster_relationships: Dict[str, List[str]]  # cluster_id -> [related_cluster_ids]
    computation_metadata: Dict[str, Any]

class TopicClusteringService:
    """
    Generalized service for clustering legal documents by topics using:
    - Legal topic co-occurrence patterns
    - Semantic embedding clustering
    - Hierarchical topic relationships
    - Document-topic membership scoring
    """

    def __init__(self, es_client):
        self.es = es_client
        self.index_name = "court-documents"
        self.topic_embeddings = {}
        self.document_topic_matrix = {}
        self._embeddings_built = False

    async def build_topic_clusters(
        self,
        min_cluster_size: int = 5,
        max_clusters: int = 50,
        similarity_threshold: float = 0.3,
        use_semantic_clustering: bool = True
    ) -> ClusterGraph:
        """
        Build topic clusters optimized for RAG consumption

        Returns complete clustering results including:
        - Hierarchical topic clusters
        - Document-cluster mappings
        - Topic similarity relationships
        - Representative cases per cluster
        - Computational metadata for LLM reasoning
        """

        # Validate parameters
        try:
            min_cluster_size = validate_positive_integer(min_cluster_size, "min_cluster_size", 2, 20)
            max_clusters = validate_positive_integer(max_clusters, "max_clusters", 1, 100)
            if not 0.0 <= similarity_threshold <= 1.0:
                raise ValueError("similarity_threshold must be between 0.0 and 1.0")
        except ValueError as e:
            logger.error(f"Invalid clustering parameters: {e}")
            raise ValueError(f"Invalid clustering parameters: {e}")

        logger.info(f"Building topic clusters from Elasticsearch (min_size={min_cluster_size}, max_clusters={max_clusters})")

        # Fetch all documents with topic data
        documents = await self._fetch_documents_with_topics()

        # Build topic co-occurrence matrix
        topic_cooccurrence = self._build_topic_cooccurrence_matrix(documents)

        # Build document-topic membership matrix
        self.document_topic_matrix = self._build_document_topic_matrix(documents)

        # Generate topic embeddings if semantic clustering enabled
        if use_semantic_clustering:
            await self._build_topic_embeddings(documents)

        # Perform clustering
        clusters = await self._perform_clustering(
            topic_cooccurrence=topic_cooccurrence,
            min_cluster_size=min_cluster_size,
            max_clusters=max_clusters,
            similarity_threshold=similarity_threshold,
            use_semantic=use_semantic_clustering
        )

        # Build topic hierarchy
        topic_hierarchy = self._build_topic_hierarchy(clusters)

        # Build document-cluster mapping
        document_cluster_mapping = self._map_documents_to_clusters(documents, clusters)

        # Calculate topic similarity matrix
        topic_similarity_matrix = self._calculate_topic_similarity_matrix(topic_cooccurrence)

        # Find cluster relationships
        cluster_relationships = self._find_cluster_relationships(clusters, topic_similarity_matrix)

        # Get representative cases for each cluster
        for cluster in clusters:
            cluster.representative_cases = await self._get_representative_cases(cluster, documents)

        return ClusterGraph(
            clusters=clusters,
            topic_hierarchy=topic_hierarchy,
            document_cluster_mapping=document_cluster_mapping,
            topic_similarity_matrix=topic_similarity_matrix,
            cluster_relationships=cluster_relationships,
            computation_metadata={
                "algorithm_version": "1.0",
                "clustering_method": "agglomerative" if use_semantic_clustering else "co_occurrence",
                "total_documents": len(documents),
                "total_unique_topics": len(topic_cooccurrence),
                "cluster_count": len(clusters),
                "parameters": {
                    "min_cluster_size": min_cluster_size,
                    "max_clusters": max_clusters,
                    "similarity_threshold": similarity_threshold,
                    "use_semantic_clustering": use_semantic_clustering
                }
            }
        )

    async def get_document_topic_clusters(self, document_id: str) -> Dict[str, Any]:
        """Get topic cluster information for a specific document"""
        # This would integrate with the main clustering results
        # For now, return basic topic analysis

        doc = await self._get_document(document_id)
        if not doc:
            return {}

        topics = self._extract_document_topics(doc)

        return {
            "document_id": document_id,
            "primary_topics": topics[:5],  # Top 5 topics
            "topic_distribution": {topic["topic"]: topic["confidence"] for topic in topics},
            "suggested_clusters": []  # Would be populated by main clustering
        }

    async def _process_documents_in_batches(self, batch_processor, batch_size: int = 100) -> None:
        """Process documents in memory-efficient batches"""
        query = {
            "query": {
                "nested": {
                    "path": "legal_topics",
                    "query": {
                        "range": {
                            "legal_topics.confidence": {"gte": 0.3}  # Minimum confidence
                        }
                    }
                }
            },
            "size": batch_size,
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_topics", "content_embedding", "document_type", "content_length"
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

        logger.info(f"Processed {total_processed} documents in batches for topic clustering")

    async def _fetch_documents_with_topics(self, batch_size: int = 1000) -> List[Dict]:
        """Fetch all documents with legal topic data - DEPRECATED: Use _process_documents_in_batches"""
        logger.warning("_fetch_documents_with_topics is deprecated. Use _process_documents_in_batches for better memory efficiency")

        documents = []

        async def collect_batch(batch):
            documents.extend(batch)

        await self._process_documents_in_batches(collect_batch, batch_size)
        return documents

    def _build_topic_cooccurrence_matrix(self, documents: List[Dict]) -> Dict[str, Dict[str, int]]:
        """Build topic co-occurrence matrix"""
        cooccurrence = defaultdict(lambda: defaultdict(int))
        topic_counts = defaultdict(int)

        for doc in documents:
            topics = self._extract_document_topics(doc, min_confidence=0.5)
            topic_names = [topic["topic"] for topic in topics]

            # Count individual topics
            for topic in topic_names:
                topic_counts[topic] += 1

            # Count co-occurrences
            for i, topic1 in enumerate(topic_names):
                for topic2 in topic_names[i+1:]:
                    cooccurrence[topic1][topic2] += 1
                    cooccurrence[topic2][topic1] += 1

        # Normalize by topic frequency (PMI-like scoring)
        normalized_cooccurrence = defaultdict(dict)
        total_docs = len(documents)

        for topic1 in cooccurrence:
            for topic2 in cooccurrence[topic1]:
                # Point-wise mutual information inspired scoring
                co_freq = cooccurrence[topic1][topic2]
                topic1_freq = topic_counts[topic1]
                topic2_freq = topic_counts[topic2]

                if co_freq > 1:  # Minimum co-occurrence threshold
                    # Normalized score
                    pmi_score = (co_freq * total_docs) / (topic1_freq * topic2_freq)
                    normalized_cooccurrence[topic1][topic2] = pmi_score

        return dict(normalized_cooccurrence)

    def _build_document_topic_matrix(self, documents: List[Dict]) -> Dict[str, Dict[str, float]]:
        """Build document-topic membership matrix"""
        doc_topic_matrix = {}

        for doc in documents:
            doc_id = str(doc["id"])
            topics = self._extract_document_topics(doc, min_confidence=0.3)

            doc_topic_matrix[doc_id] = {
                topic["topic"]: topic["confidence"]
                for topic in topics
            }

        return doc_topic_matrix

    async def _build_topic_embeddings(self, documents: List[Dict]) -> None:
        """Build semantic embeddings for topics using document embeddings"""
        if self._embeddings_built:
            return

        topic_document_embeddings = defaultdict(list)

        # Collect embeddings for each topic
        for doc in documents:
            embedding = doc.get("content_embedding")
            if not embedding:
                continue

            topics = self._extract_document_topics(doc, min_confidence=0.5)
            for topic in topics:
                topic_name = topic["topic"]
                confidence = topic["confidence"]

                # Weight embedding by confidence
                weighted_embedding = np.array(embedding) * confidence
                topic_document_embeddings[topic_name].append(weighted_embedding)

        # Calculate average embeddings for each topic
        self.topic_embeddings = {}
        for topic, embeddings in topic_document_embeddings.items():
            if len(embeddings) >= 2:  # Minimum documents per topic
                avg_embedding = np.mean(embeddings, axis=0)
                self.topic_embeddings[topic] = avg_embedding.tolist()

        self._embeddings_built = True
        logger.info(f"Built embeddings for {len(self.topic_embeddings)} topics")

    async def _perform_clustering(
        self,
        topic_cooccurrence: Dict[str, Dict[str, int]],
        min_cluster_size: int,
        max_clusters: int,
        similarity_threshold: float,
        use_semantic: bool
    ) -> List[TopicCluster]:
        """Perform topic clustering using multiple methods"""

        if use_semantic and self.topic_embeddings:
            clusters = await self._semantic_clustering(
                min_cluster_size=min_cluster_size,
                max_clusters=max_clusters
            )
        else:
            clusters = await self._cooccurrence_clustering(
                topic_cooccurrence=topic_cooccurrence,
                similarity_threshold=similarity_threshold,
                min_cluster_size=min_cluster_size
            )

        # Calculate coherence scores
        for cluster in clusters:
            cluster.coherence_score = self._calculate_cluster_coherence(
                cluster.topic_names, topic_cooccurrence
            )

        return clusters

    async def _semantic_clustering(self, min_cluster_size: int, max_clusters: int) -> List[TopicCluster]:
        """Perform semantic clustering using topic embeddings"""
        if not self.topic_embeddings:
            return []

        topics = list(self.topic_embeddings.keys())
        embeddings = np.array([self.topic_embeddings[topic] for topic in topics])

        # Normalize embeddings
        scaler = StandardScaler()
        embeddings_scaled = scaler.fit_transform(embeddings)

        # Agglomerative clustering
        clustering = AgglomerativeClustering(
            n_clusters=min(max_clusters, len(topics)),
            linkage="ward"
        )

        cluster_labels = clustering.fit_predict(embeddings_scaled)

        # Group topics by cluster
        clusters_dict = defaultdict(list)
        for topic, label in zip(topics, cluster_labels):
            clusters_dict[label].append(topic)

        # Create TopicCluster objects
        clusters = []
        for cluster_id, topic_names in clusters_dict.items():
            if len(topic_names) >= min_cluster_size:
                # Calculate cluster center
                cluster_embeddings = [self.topic_embeddings[topic] for topic in topic_names]
                cluster_center = np.mean(cluster_embeddings, axis=0).tolist()

                # Get documents for these topics
                document_ids = self._get_documents_for_topics(topic_names)

                clusters.append(TopicCluster(
                    cluster_id=f"semantic_cluster_{cluster_id}",
                    topic_names=topic_names,
                    document_ids=document_ids,
                    cluster_center=cluster_center,
                    coherence_score=0.0,  # Will be calculated later
                    size=len(document_ids),
                    representative_cases=[]  # Will be populated later
                ))

        return clusters

    async def _cooccurrence_clustering(
        self,
        topic_cooccurrence: Dict[str, Dict[str, int]],
        similarity_threshold: float,
        min_cluster_size: int
    ) -> List[TopicCluster]:
        """Perform clustering based on topic co-occurrence patterns"""

        # Build graph from co-occurrence matrix
        G = nx.Graph()

        for topic1 in topic_cooccurrence:
            G.add_node(topic1)
            for topic2, weight in topic_cooccurrence[topic1].items():
                if weight >= similarity_threshold:
                    G.add_edge(topic1, topic2, weight=weight)

        # Find connected components as clusters
        clusters = []
        cluster_id = 0

        for component in nx.connected_components(G):
            topic_names = list(component)
            if len(topic_names) >= min_cluster_size:
                document_ids = self._get_documents_for_topics(topic_names)

                clusters.append(TopicCluster(
                    cluster_id=f"cooccurrence_cluster_{cluster_id}",
                    topic_names=topic_names,
                    document_ids=document_ids,
                    cluster_center=None,
                    coherence_score=0.0,  # Will be calculated later
                    size=len(document_ids),
                    representative_cases=[]  # Will be populated later
                ))
                cluster_id += 1

        return clusters

    def _get_documents_for_topics(self, topic_names: List[str]) -> List[str]:
        """Get document IDs that contain any of the specified topics"""
        document_ids = set()

        for doc_id, topic_scores in self.document_topic_matrix.items():
            for topic in topic_names:
                if topic in topic_scores and topic_scores[topic] >= 0.5:
                    document_ids.add(doc_id)
                    break  # Document matches cluster

        return list(document_ids)

    def _calculate_cluster_coherence(
        self,
        topic_names: List[str],
        topic_cooccurrence: Dict[str, Dict[str, int]]
    ) -> float:
        """Calculate cluster coherence based on internal topic co-occurrence"""
        if len(topic_names) < 2:
            return 1.0

        total_pairs = 0
        coherence_sum = 0.0

        for i, topic1 in enumerate(topic_names):
            for topic2 in topic_names[i+1:]:
                total_pairs += 1
                if topic1 in topic_cooccurrence and topic2 in topic_cooccurrence[topic1]:
                    coherence_sum += topic_cooccurrence[topic1][topic2]

        return coherence_sum / total_pairs if total_pairs > 0 else 0.0

    def _build_topic_hierarchy(self, clusters: List[TopicCluster]) -> Dict[str, List[str]]:
        """Build hierarchical topic relationships"""
        hierarchy = {}

        # Simple approach: group clusters by semantic similarity
        for cluster in clusters:
            # Use first topic as representative
            if cluster.topic_names:
                parent_topic = cluster.topic_names[0]
                child_topics = cluster.topic_names[1:] if len(cluster.topic_names) > 1 else []
                hierarchy[parent_topic] = child_topics

        return hierarchy

    def _map_documents_to_clusters(
        self,
        documents: List[Dict],
        clusters: List[TopicCluster]
    ) -> Dict[str, str]:
        """Map documents to their best-fitting cluster"""
        doc_cluster_mapping = {}

        for doc in documents:
            doc_id = str(doc["id"])
            doc_topics = self._extract_document_topics(doc, min_confidence=0.5)
            doc_topic_names = {topic["topic"] for topic in doc_topics}

            best_cluster = None
            best_overlap = 0

            for cluster in clusters:
                cluster_topics = set(cluster.topic_names)
                overlap = len(doc_topic_names.intersection(cluster_topics))

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_cluster = cluster

            if best_cluster and best_overlap > 0:
                doc_cluster_mapping[doc_id] = best_cluster.cluster_id

        return doc_cluster_mapping

    def _calculate_topic_similarity_matrix(
        self,
        topic_cooccurrence: Dict[str, Dict[str, int]]
    ) -> Dict[str, Dict[str, float]]:
        """Calculate pairwise topic similarity matrix"""
        similarity_matrix = {}

        all_topics = set(topic_cooccurrence.keys())
        for topic2 in topic_cooccurrence.values():
            all_topics.update(topic2.keys())

        for topic1 in all_topics:
            similarity_matrix[topic1] = {}
            for topic2 in all_topics:
                if topic1 == topic2:
                    similarity_matrix[topic1][topic2] = 1.0
                elif (topic1 in topic_cooccurrence and
                      topic2 in topic_cooccurrence[topic1]):
                    similarity_matrix[topic1][topic2] = topic_cooccurrence[topic1][topic2]
                else:
                    similarity_matrix[topic1][topic2] = 0.0

        return similarity_matrix

    def _find_cluster_relationships(
        self,
        clusters: List[TopicCluster],
        topic_similarity_matrix: Dict[str, Dict[str, float]]
    ) -> Dict[str, List[str]]:
        """Find relationships between clusters"""
        relationships = {}

        for i, cluster1 in enumerate(clusters):
            related_clusters = []

            for j, cluster2 in enumerate(clusters):
                if i != j:
                    # Calculate inter-cluster similarity
                    similarity = self._calculate_inter_cluster_similarity(
                        cluster1.topic_names,
                        cluster2.topic_names,
                        topic_similarity_matrix
                    )

                    if similarity > 0.1:  # Threshold for related clusters
                        related_clusters.append(cluster2.cluster_id)

            relationships[cluster1.cluster_id] = related_clusters

        return relationships

    def _calculate_inter_cluster_similarity(
        self,
        topics1: List[str],
        topics2: List[str],
        similarity_matrix: Dict[str, Dict[str, float]]
    ) -> float:
        """Calculate similarity between two topic clusters"""
        similarities = []

        for topic1 in topics1:
            for topic2 in topics2:
                if (topic1 in similarity_matrix and
                    topic2 in similarity_matrix[topic1]):
                    similarities.append(similarity_matrix[topic1][topic2])

        return np.mean(similarities) if similarities else 0.0

    async def _get_representative_cases(
        self,
        cluster: TopicCluster,
        documents: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Get representative cases for a cluster"""
        cluster_docs = []

        for doc in documents:
            doc_id = str(doc["id"])
            if doc_id in cluster.document_ids:
                doc_topics = self._extract_document_topics(doc, min_confidence=0.5)
                topic_names = {topic["topic"] for topic in doc_topics}

                # Calculate overlap with cluster topics
                overlap = len(topic_names.intersection(set(cluster.topic_names)))
                overlap_ratio = overlap / len(cluster.topic_names) if cluster.topic_names else 0

                cluster_docs.append({
                    "document_id": doc_id,
                    "case_name": doc.get("case_name"),
                    "overlap_ratio": overlap_ratio,
                    "metadata": {
                        "judge_name": doc.get("judge_name"),
                        "court_id": doc.get("court_id"),
                        "filing_date": doc.get("filing_date"),
                        "content_length": doc.get("content_length", 0)
                    }
                })

        # Sort by overlap ratio and return top cases
        cluster_docs.sort(key=lambda x: x["overlap_ratio"], reverse=True)
        return cluster_docs[:5]  # Top 5 representative cases

    def _extract_document_topics(self, doc: Dict, min_confidence: float = 0.3) -> List[Dict]:
        """Extract topics from document with confidence filtering"""
        topics = []
        raw_topics = doc.get("legal_topics", []) or []

        for topic in raw_topics:
            if isinstance(topic, dict):
                confidence = topic.get("confidence", 0.0)
                topic_name = topic.get("topic")

                if topic_name and confidence >= min_confidence:
                    topics.append({
                        "topic": topic_name,
                        "confidence": confidence
                    })

        # Sort by confidence
        topics.sort(key=lambda x: x["confidence"], reverse=True)
        return topics

    async def _get_document(self, document_id: str) -> Optional[Dict]:
        """Get single document by ID"""
        query = {
            "query": {"term": {"id": document_id}},
            "size": 1,
            "_source": [
                "id", "case_name", "judge_name", "court_id", "filing_date",
                "legal_topics", "content_embedding", "document_type", "content_length"
            ]
        }

        try:
            response = await self.es.search(index=self.index_name, body=query)
            hits = response["hits"]["hits"]
            return hits[0]["_source"] if hits else None
        except Exception as e:
            logger.error(f"Failed to fetch document {document_id}: {e}")
            return None

    async def get_clustering_statistics(self) -> Dict[str, Any]:
        """Get clustering statistics for monitoring and debugging"""
        # This would be called after clustering is complete
        return {
            "topic_embeddings": {
                "available": len(self.topic_embeddings),
                "dimensions": len(next(iter(self.topic_embeddings.values()))) if self.topic_embeddings else 0
            },
            "document_topic_matrix": {
                "documents": len(self.document_topic_matrix),
                "average_topics_per_doc": np.mean([
                    len(topics) for topics in self.document_topic_matrix.values()
                ]) if self.document_topic_matrix else 0
            }
        }