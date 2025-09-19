"""
Input validation models for legal analytics services

Provides Pydantic models for validating and sanitizing inputs to all analytics services,
preventing crashes and security issues from malformed or malicious inputs.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
import re

class DocumentIDValidator(BaseModel):
    """Validates document ID format and existence"""
    document_id: str = Field(..., min_length=1, max_length=256, description="Document identifier")

    @validator('document_id')
    def validate_document_id_format(cls, v):
        # Allow alphanumeric, hyphens, underscores, and dots
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Document ID contains invalid characters. Only alphanumeric, dots, hyphens, and underscores allowed.')
        return v.strip()

class RecommendationRequest(BaseModel):
    """Validates case recommendation requests"""
    document_id: str = Field(..., min_length=1, max_length=256)
    max_recommendations: int = Field(20, ge=1, le=100, description="Maximum number of recommendations to return")
    min_score_threshold: float = Field(0.1, ge=0.0, le=1.0, description="Minimum similarity score threshold")
    include_full_graph: bool = Field(True, description="Whether to include full graph data")

    @validator('document_id')
    def validate_document_id_format(cls, v):
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Document ID contains invalid characters')
        return v.strip()

class CitationAnalysisRequest(BaseModel):
    """Validates citation analysis requests"""
    document_id: str = Field(..., min_length=1, max_length=256)
    analysis_depth: str = Field("standard", regex="^(basic|standard|comprehensive)$")
    include_network: bool = Field(True, description="Include citation network analysis")
    min_citation_confidence: float = Field(0.5, ge=0.0, le=1.0)

    @validator('document_id')
    def validate_document_id_format(cls, v):
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Document ID contains invalid characters')
        return v.strip()

class TopicClusteringRequest(BaseModel):
    """Validates topic clustering requests"""
    key: str = Field(..., min_length=1, max_length=100, description="Clustering key/identifier")
    max_clusters: int = Field(20, ge=1, le=50, description="Maximum number of clusters to generate")
    min_cluster_size: int = Field(3, ge=2, le=20, description="Minimum documents per cluster")
    algorithm: str = Field("community", regex="^(community|kmeans|hierarchical)$")
    min_topic_confidence: float = Field(0.5, ge=0.0, le=1.0)

    @validator('key')
    def validate_key_format(cls, v):
        # Allow alphanumeric and basic punctuation for clustering keys
        if not re.match(r'^[a-zA-Z0-9._\-\s]+$', v):
            raise ValueError('Clustering key contains invalid characters')
        return v.strip()

class SearchRequest(BaseModel):
    """Validates search requests"""
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    max_results: int = Field(20, ge=1, le=100, description="Maximum results to return")
    search_profile: str = Field("basic", regex="^(basic|professional|advanced|research|litigation)$")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional search filters")

    @validator('query')
    def validate_query_content(cls, v):
        # Basic sanitization - remove potential script tags and normalize whitespace
        v = re.sub(r'<[^>]*>', '', v)  # Remove HTML tags
        v = re.sub(r'\s+', ' ', v)     # Normalize whitespace
        v = v.strip()

        if not v:
            raise ValueError('Query cannot be empty after sanitization')

        return v

    @validator('filters')
    def validate_filters(cls, v):
        if v is None:
            return v

        # Validate filter structure
        allowed_filter_keys = {
            'date_range', 'court_id', 'judge_name', 'document_type',
            'jurisdiction', 'case_type', 'topic_filter'
        }

        for key in v.keys():
            if key not in allowed_filter_keys:
                raise ValueError(f'Invalid filter key: {key}')

        return v

class BatchProcessingConfig(BaseModel):
    """Validates batch processing configuration"""
    batch_size: int = Field(100, ge=1, le=1000, description="Number of documents per batch")
    max_total_documents: int = Field(10000, ge=1, le=50000, description="Maximum total documents to process")
    timeout_seconds: int = Field(300, ge=30, le=3600, description="Processing timeout in seconds")

class ElasticsearchConfig(BaseModel):
    """Validates Elasticsearch configuration parameters"""
    index_name: str = Field("court-documents", min_length=1, max_length=100)
    scroll_timeout: str = Field("5m", regex="^[0-9]+[smh]$")
    scroll_size: int = Field(1000, ge=10, le=10000)

    @validator('index_name')
    def validate_index_name(cls, v):
        # Elasticsearch index naming rules
        if not re.match(r'^[a-z0-9._-]+$', v):
            raise ValueError('Index name must be lowercase and contain only letters, numbers, dots, hyphens, and underscores')
        if v.startswith(('.', '_', '-')):
            raise ValueError('Index name cannot start with dots, underscores, or hyphens')
        return v

def validate_document_id(document_id: str) -> str:
    """Quick validation helper for document IDs"""
    validator = DocumentIDValidator(document_id=document_id)
    return validator.document_id

def validate_confidence_score(score: float, field_name: str = "confidence") -> float:
    """Quick validation helper for confidence scores"""
    if not isinstance(score, (int, float)):
        raise ValueError(f'{field_name} must be a number')
    if not 0.0 <= score <= 1.0:
        raise ValueError(f'{field_name} must be between 0.0 and 1.0')
    return float(score)

def validate_positive_integer(value: int, field_name: str, min_val: int = 1, max_val: int = 10000) -> int:
    """Quick validation helper for positive integers with bounds"""
    if not isinstance(value, int):
        raise ValueError(f'{field_name} must be an integer')
    if not min_val <= value <= max_val:
        raise ValueError(f'{field_name} must be between {min_val} and {max_val}')
    return value