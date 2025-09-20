"""
Input validation models for legal analytics services

Provides additional Pydantic models for validating and sanitizing inputs to analytics services.
This module extends the base validation framework with utility classes and helpers.
Main validation classes are now in base_validation.py to avoid duplication.
"""

from typing import Optional, Dict, Any
from pydantic import Field, validator
import re

# Import base validation classes and mixins
from .base_validation import (
    BaseAnalyticsRequest,
    BaseBatchRequest,
    BaseSearchRequest,
    ValidationMixin,
    BaseModel,
    # Re-export the main request classes for backward compatibility
    RecommendationRequest,
    CitationAnalysisRequest,
    TopicClusteringRequest,
    SearchRequest
)

# Re-export for backward compatibility
__all__ = [
    'RecommendationRequest',
    'CitationAnalysisRequest',
    'TopicClusteringRequest',
    'SearchRequest',
    'DocumentIDValidator',
    'BatchProcessingConfig',
    'ElasticsearchConfig',
    'validate_document_id',
    'validate_confidence_score',
    'validate_positive_integer'
]

class DocumentIDValidator(BaseModel, ValidationMixin):
    """Validates document ID format and existence"""
    document_id: str = Field(..., min_length=1, max_length=256, description="Document identifier")

    @validator('document_id')
    def validate_document_id(cls, v):
        return cls.validate_document_id_format(v)

class BatchProcessingConfig(BaseBatchRequest):
    """Validates batch processing configuration - extends BaseBatchRequest"""
    # Inherits batch_size, max_total_items (renamed from max_total_documents), timeout_seconds
    pass

class ElasticsearchConfig(BaseModel, ValidationMixin):
    """Validates Elasticsearch configuration parameters"""
    index_name: str = Field("court-documents", min_length=1, max_length=100)
    scroll_timeout: str = Field("5m", pattern="^[0-9]+[smh]$")
    scroll_size: int = Field(1000, ge=10, le=10000)

    @validator('index_name')
    def validate_index_name(cls, v):
        # Elasticsearch index naming rules
        if not re.match(r'^[a-z0-9._-]+$', v):
            raise ValueError('Index name must be lowercase and contain only letters, numbers, dots, hyphens, and underscores')
        if v.startswith(('.', '_', '-')):
            raise ValueError('Index name cannot start with dots, underscores, or hyphens')
        return v

    @validator('scroll_size')
    def validate_scroll_size(cls, v):
        return cls.validate_positive_integer_range(v, "scroll_size", 10, 10000)

# Convenience validation functions - now delegating to ValidationMixin methods
def validate_document_id(document_id: str) -> str:
    """Quick validation helper for document IDs"""
    return ValidationMixin.validate_document_id_format(document_id)

def validate_confidence_score(score: float, field_name: str = "confidence") -> float:
    """Quick validation helper for confidence scores"""
    return ValidationMixin.validate_confidence_range(score, field_name)

def validate_positive_integer(value: int, field_name: str, min_val: int = 1, max_val: int = 10000) -> int:
    """Quick validation helper for positive integers with bounds"""
    return ValidationMixin.validate_positive_integer_range(value, field_name, min_val, max_val)