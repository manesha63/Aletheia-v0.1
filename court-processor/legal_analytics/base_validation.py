"""
Base Validation Framework for Legal Analytics

Provides reusable validation components, mixins, and base classes to eliminate
duplication and ensure consistent validation across all analytics services.
"""

from typing import Dict, List, Optional, Any, Union, Callable
from pydantic import BaseModel, Field, validator, root_validator
import re
import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class ValidationMixin:
    """Mixin providing common validation methods"""

    @staticmethod
    def validate_document_id_format(v: str) -> str:
        """Shared document ID validation logic"""
        if not isinstance(v, str):
            raise ValueError('Document ID must be a string')
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Document ID contains invalid characters. Only alphanumeric, dots, hyphens, and underscores allowed.')
        return v.strip()

    @staticmethod
    def validate_confidence_range(v: float, field_name: str = "confidence") -> float:
        """Shared confidence score validation"""
        if not isinstance(v, (int, float)):
            raise ValueError(f'{field_name} must be a number')
        if not 0.0 <= v <= 1.0:
            raise ValueError(f'{field_name} must be between 0.0 and 1.0')
        return float(v)

    @staticmethod
    def validate_positive_integer_range(v: int, field_name: str, min_val: int = 1, max_val: int = 10000) -> int:
        """Shared positive integer validation with bounds"""
        if not isinstance(v, int):
            raise ValueError(f'{field_name} must be an integer')
        if not min_val <= v <= max_val:
            raise ValueError(f'{field_name} must be between {min_val} and {max_val}')
        return v

    @staticmethod
    def sanitize_query_string(v: str) -> str:
        """Shared query sanitization logic"""
        # Remove HTML tags
        v = re.sub(r'<[^>]*>', '', v)
        # Normalize whitespace
        v = re.sub(r'\s+', ' ', v)
        # Remove potentially dangerous patterns
        v = re.sub(r'[<>"\';]', '', v)
        return v.strip()

class BaseDocumentRequest(BaseModel, ValidationMixin):
    """Base class for all document-related requests"""

    document_id: str = Field(..., min_length=1, max_length=256, description="Document identifier")

    @validator('document_id')
    def validate_document_id(cls, v):
        return cls.validate_document_id_format(v)

class BaseBatchRequest(BaseModel, ValidationMixin):
    """Base class for requests involving batch processing"""

    batch_size: int = Field(100, ge=1, le=1000, description="Batch size for processing")
    max_total_items: int = Field(10000, ge=1, le=50000, description="Maximum total items to process")
    timeout_seconds: int = Field(300, ge=30, le=3600, description="Processing timeout")

    @validator('batch_size')
    def validate_batch_size(cls, v):
        return cls.validate_positive_integer_range(v, "batch_size", 1, 1000)

    @validator('max_total_items')
    def validate_max_total_items(cls, v):
        return cls.validate_positive_integer_range(v, "max_total_items", 1, 50000)

    @validator('timeout_seconds')
    def validate_timeout(cls, v):
        return cls.validate_positive_integer_range(v, "timeout_seconds", 30, 3600)

class BaseAnalyticsRequest(BaseDocumentRequest):
    """Base class for analytics service requests"""

    include_metadata: bool = Field(True, description="Include computational metadata in response")
    min_confidence: float = Field(0.1, ge=0.0, le=1.0, description="Minimum confidence threshold")

    @validator('min_confidence')
    def validate_confidence(cls, v):
        return cls.validate_confidence_range(v, "min_confidence")

class BaseSearchRequest(BaseModel, ValidationMixin):
    """Base class for search-related requests"""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    max_results: int = Field(20, ge=1, le=100, description="Maximum results to return")
    offset: int = Field(0, ge=0, le=10000, description="Result offset for pagination")

    @validator('query')
    def validate_and_sanitize_query(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("Query must be a non-empty string")
        sanitized = cls.sanitize_query_string(v)
        if not sanitized:
            raise ValueError("Query cannot be empty after sanitization")
        return sanitized

    @validator('max_results')
    def validate_max_results(cls, v):
        return cls.validate_positive_integer_range(v, "max_results", 1, 100)

    @validator('offset')
    def validate_offset(cls, v):
        return cls.validate_positive_integer_range(v, "offset", 0, 10000)

class AsyncValidator(ABC):
    """Abstract base for async validation operations"""

    @abstractmethod
    async def validate(self, value: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Perform async validation"""
        pass

class DocumentExistenceValidator(AsyncValidator):
    """Async validator to check if document exists in Elasticsearch"""

    def __init__(self, es_client, index_name: str = "court-documents"):
        self.es = es_client
        self.index_name = index_name

    async def validate(self, document_id: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Validate that document exists in Elasticsearch"""
        try:
            response = await self.es.get(
                index=self.index_name,
                id=document_id,
                _source=False  # We only need to check existence
            )
            return document_id
        except Exception as e:
            logger.warning(f"Document {document_id} not found: {e}")
            raise ValueError(f"Document {document_id} does not exist")

class ValidationContext:
    """Context manager for validation operations"""

    def __init__(self):
        self.validators: Dict[str, AsyncValidator] = {}
        self.es_client = None

    def add_validator(self, name: str, validator: AsyncValidator):
        """Add an async validator"""
        self.validators[name] = validator

    def set_es_client(self, es_client):
        """Set Elasticsearch client for document validation"""
        self.es_client = es_client
        # Add document existence validator
        self.add_validator(
            "document_exists",
            DocumentExistenceValidator(es_client)
        )

    async def validate_document_exists(self, document_id: str) -> str:
        """Convenience method for document existence validation"""
        if "document_exists" in self.validators:
            return await self.validators["document_exists"].validate(document_id)
        return document_id  # Skip validation if no ES client

# Specific request models using the base classes
class RecommendationRequest(BaseAnalyticsRequest):
    """Validates case recommendation requests"""
    max_recommendations: int = Field(20, ge=1, le=100)
    include_full_graph: bool = Field(True)

    @validator('max_recommendations')
    def validate_max_recommendations(cls, v):
        return cls.validate_positive_integer_range(v, "max_recommendations", 1, 100)

class CitationAnalysisRequest(BaseAnalyticsRequest):
    """Validates citation analysis requests"""
    analysis_depth: str = Field("standard", regex="^(basic|standard|comprehensive)$")
    include_network: bool = Field(True)

class TopicClusteringRequest(BaseBatchRequest):
    """Validates topic clustering requests"""
    key: str = Field(..., min_length=1, max_length=100, description="Clustering key")
    max_clusters: int = Field(20, ge=1, le=50)
    min_cluster_size: int = Field(3, ge=2, le=20)
    algorithm: str = Field("community", regex="^(community|kmeans|hierarchical)$")
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)

    @validator('key')
    def validate_key_format(cls, v):
        if not re.match(r'^[a-zA-Z0-9._\-\s]+$', v):
            raise ValueError('Clustering key contains invalid characters')
        return v.strip()

    @validator('max_clusters')
    def validate_max_clusters(cls, v):
        return cls.validate_positive_integer_range(v, "max_clusters", 1, 50)

    @validator('min_cluster_size')
    def validate_min_cluster_size(cls, v):
        return cls.validate_positive_integer_range(v, "min_cluster_size", 2, 20)

    @validator('min_confidence')
    def validate_min_confidence(cls, v):
        return cls.validate_confidence_range(v, "min_confidence")

class SearchRequest(BaseSearchRequest):
    """Validates search requests"""
    search_profile: str = Field("basic", regex="^(basic|professional|advanced|research|litigation)$")
    filters: Optional[Dict[str, Any]] = Field(None)

    @validator('filters')
    def validate_filters(cls, v):
        if v is None:
            return v

        allowed_keys = {
            'date_range', 'court_id', 'judge_name', 'document_type',
            'jurisdiction', 'case_type', 'topic_filter'
        }

        for key in v.keys():
            if key not in allowed_keys:
                raise ValueError(f'Invalid filter key: {key}')

        return v

# Convenience validation functions
def validate_request(request_class: type, data: Dict[str, Any]) -> BaseModel:
    """Validate request data against a request class"""
    try:
        return request_class(**data)
    except Exception as e:
        logger.error(f"Validation failed for {request_class.__name__}: {e}")
        raise ValueError(f"Invalid request parameters: {e}")

async def validate_with_context(
    request_class: type,
    data: Dict[str, Any],
    validation_context: Optional[ValidationContext] = None
) -> BaseModel:
    """Validate request with optional async validations"""
    # First, validate the basic structure
    validated_request = validate_request(request_class, data)

    # Then perform async validations if context provided
    if validation_context and hasattr(validated_request, 'document_id'):
        await validation_context.validate_document_exists(validated_request.document_id)

    return validated_request

# Global validation context
_validation_context = ValidationContext()

def get_validation_context() -> ValidationContext:
    """Get the global validation context"""
    return _validation_context

def set_es_client_for_validation(es_client):
    """Set ES client for global validation context"""
    _validation_context.set_es_client(es_client)