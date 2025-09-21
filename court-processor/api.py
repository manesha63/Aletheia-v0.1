#!/usr/bin/env python3
"""
Simplified Court Documents API - Direct access to long-form legal content

Key improvements:
1. Direct text access via /text/{id} endpoint
2. Flatter response structure
3. Content-type based responses (text/plain option)
4. Simpler search with direct text field
"""

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
import os
from elasticsearch import Elasticsearch
from search_features import AISearchEngine, SearchProfiles, SearchFeature, SearchConfig
from legal_analytics import RelatedCaseService, TopicClusteringService, CitationAnalyticsService
import logging
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
# Use 'db' as default host for Docker environments, 'localhost' for local development
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'db' if os.path.exists('/.dockerenv') else 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),  # PostgreSQL default port
    'database': os.getenv('DB_NAME', 'aletheia'),
    'user': os.getenv('DB_USER', 'aletheia'),
    'password': os.getenv('DB_PASSWORD', 'aletheia123')
}

# Elasticsearch configuration
ES_CONFIG = {
    'host': os.getenv('ES_HOST', 'elasticsearch-judicial' if os.path.exists('/.dockerenv') else 'localhost'),
    'port': os.getenv('ES_PORT', '9200'),
    'index': os.getenv('ES_INDEX', 'court-documents')
}

API_PORT = int(os.getenv('SIMPLE_API_PORT', '8104'))

# Initialize FastAPI
app = FastAPI(
    title="Simplified Court Documents API",
    description="Direct, simple access to full-text court opinions",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_db_connection():
    """Create database connection"""
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

def get_es_client():
    """Create Elasticsearch client"""
    try:
        es_url = f"http://{ES_CONFIG['host']}:{ES_CONFIG['port']}"
        # Create ES client compatible with ES 8.17.1 server
        return Elasticsearch([es_url])
    except Exception as e:
        logger.error(f"Elasticsearch connection failed: {e}")
        raise

def extract_plain_text(html_content: str) -> str:
    """Extract plain text from HTML/XML content"""
    if not html_content:
        return ""
    
    # Remove script and style elements
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    
    # Remove all HTML/XML tags more aggressively
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()

def extract_document_type(text: str, limit: int = 500) -> str:
    """
    Extract document type from the beginning of document text
    
    Args:
        text: Plain text content of the document
        limit: Number of characters to search within
        
    Returns:
        Formatted document type string
    """
    if not text:
        return "Opinion"
    
    # Get first N characters for analysis
    text_start = text[:limit].upper()
    
    # Document type patterns (ordered by specificity)
    patterns = [
        (r'MEMORANDUM\s+OPINION\s+AND\s+ORDER', 'Memorandum Opinion and Order'),
        (r'CLAIM\s+CONSTRUCTION\s+(ORDER|OPINION)', 'Claim Construction Order'),
        (r'SUMMARY\s+JUDGMENT', 'Summary Judgment Order'),
        (r'MOTION\s+TO\s+DISMISS', 'Motion to Dismiss Order'),
        (r'FINDINGS\s+OF\s+FACT\s+AND\s+CONCLUSIONS\s+OF\s+LAW', 'Findings and Conclusions'),
        (r'MEMORANDUM\s+AND\s+ORDER', 'Memorandum and Order'),
        (r'MEMORANDUM\s+OPINION', 'Memorandum Opinion'),
        (r'ORDER\s+AND\s+OPINION', 'Order and Opinion'),
        (r'FINAL\s+JUDGMENT', 'Final Judgment'),
        (r'JUDGMENT', 'Judgment'),
        (r'ORDER', 'Order'),
        (r'OPINION', 'Opinion'),
    ]
    
    for pattern, doc_type in patterns:
        if re.search(pattern, text_start):
            return doc_type
    
    return "Opinion"  # Default fallback

def format_legal_title(
    case_name: Optional[str] = None,
    document_type: Optional[str] = None,
    judge_name: Optional[str] = None,
    date_filed: Optional[str] = None,
    court_id: Optional[str] = None,
    short_form: bool = False
) -> str:
    """
    Format a legal document title following citation standards
    
    Args:
        case_name: Full case name (e.g., "Core Wireless v. LG Electronics")
        document_type: Type of document (e.g., "Memorandum Opinion and Order")
        judge_name: Judge's name
        date_filed: Filing date in YYYY-MM-DD format
        court_id: Court identifier
        short_form: If True, return abbreviated format
        
    Returns:
        Formatted legal citation title
    """
    if not case_name:
        return "Untitled Document"
    
    # Clean any residual HTML from case_name
    if '<' in case_name and '>' in case_name:
        # Remove any HTML tags that might have slipped through
        case_name = re.sub(r'<[^>]+>', '', case_name).strip()
        # Also remove any text that looks like it's from HTML content
        if case_name.startswith('After a jury trial') or 'Fed. R. Civ. P.' in case_name:
            # This is content, not a case name - return generic
            case_name = "Court Document"
    
    # Shorten case name if needed (remove extra parties after first v.)
    if short_form and ' v. ' in case_name:
        parts = case_name.split(' v. ')
        if len(parts) >= 2:
            # Take first plaintiff and first defendant
            plaintiff = parts[0].split(',')[0].strip()
            defendant = parts[1].split(',')[0].strip()
            case_name = f"{plaintiff} v. {defendant}"
    
    # Build title components
    title_parts = [case_name]
    
    if document_type:
        title_parts.append(f" - {document_type}")
    
    # Add judge and/or court (but not for short form - UI already shows judge context)
    if not short_form and (judge_name or court_id):
        attribution = []
        if judge_name:
            # Extract last name if full name provided
            if ' ' in judge_name:
                judge_name = judge_name.split()[-1]
            attribution.append(judge_name)
        elif court_id:
            # Format court ID nicely
            court_map = {
                'txed': 'E.D. Tex.',
                'txwd': 'W.D. Tex.',
                'txnd': 'N.D. Tex.',
                'txsd': 'S.D. Tex.',
            }
            attribution.append(court_map.get(court_id, court_id.upper()))
        
        if attribution:
            title_parts.append(f", {' '.join(attribution)}")
    
    # Add date if available
    if date_filed:
        if short_form:
            # Extract year only for short form
            year = date_filed[:4] if len(date_filed) >= 4 else date_filed
            title_parts.append(f" ({year})")
        else:
            title_parts.append(f" ({date_filed})")
    
    return ''.join(title_parts)

# ============= SIMPLIFIED ENDPOINTS =============

@app.get("/")
async def health():
    """Simple health check"""
    return {
        "status": "healthy",
        "api": "Simplified Court Documents API v2",
        "endpoints": {
            "GET /text/{id}": "Get plain text directly",
            "GET /documents/{id}": "Get full document info with XML metadata",
            "GET /search": "Simple search with direct text",
            "GET /list": "List recent documents",
            "GET /bulk/judge/{name}": "Bulk retrieval by judge with XML metadata",
            "GET /sample": "Sample document for testing"
        },
        "features": {
            "xml_metadata": "Rich legal metadata (citations, motions, rules)",
            "bulk_export": "Large-scale data retrieval by judge",
            "full_text": "Complete document content extraction"
        }
    }

@app.get("/text/{document_id}", response_class=Response)
async def get_text_only(document_id: int, format: str = "plain"):
    """
    Direct access to document text - returns ONLY the text content
    
    Usage:
    - /text/420 - returns plain text directly
    - /text/420?format=json - returns {"text": "...", "length": 12345}
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT content
            FROM public.court_documents
            WHERE id = %s
        """, (document_id,))
        
        doc = cur.fetchone()
        cur.close()
        conn.close()
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        text = extract_plain_text(doc['content'])
        
        if format == "json":
            return {"text": text, "length": len(text)}
        else:
            # Return plain text directly
            return Response(content=text, media_type="text/plain")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get text: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{document_id}")
async def get_document_simple(document_id: int):
    """
    Get document with simplified structure
    
    Returns flat structure with direct access to text
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                id,
                case_number,
                document_type,
                content,
                metadata,
                created_at
            FROM public.court_documents
            WHERE id = %s
        """, (document_id,))
        
        doc = cur.fetchone()
        cur.close()
        conn.close()
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Parse metadata
        metadata = doc['metadata'] if isinstance(doc['metadata'], dict) else json.loads(doc['metadata'] or '{}')
        
        # Extract text
        text = extract_plain_text(doc['content'])
        
        # Extract document type from text
        document_type_from_text = extract_document_type(text)
        
        # Get case name (prefer metadata.case_name, fallback to case_number)
        case_name = metadata.get('case_name') or doc['case_number'] or f"Document-{doc['id']}"
        
        # Format the enhanced title
        formatted_title = format_legal_title(
            case_name=case_name,
            document_type=document_type_from_text,
            judge_name=metadata.get('judge_name'),
            date_filed=metadata.get('date_filed'),
            court_id=metadata.get('court_id')
        )
        
        # Format short title for UI
        formatted_title_short = format_legal_title(
            case_name=case_name,
            document_type=document_type_from_text,
            judge_name=metadata.get('judge_name'),
            date_filed=metadata.get('date_filed'),
            court_id=metadata.get('court_id'),
            short_form=True
        )
        
        # FLAT, SIMPLE structure with backwards compatibility
        return {
            "id": doc['id'],
            "case_number": doc['case_number'],  # Keep for backwards compatibility
            "type": doc['document_type'],
            "text": text,  # Direct access to full text
            "text_length": len(text),
            "judge": metadata.get('judge_name', 'Unknown'),
            "court": metadata.get('court_id', 'Unknown'),
            "date_filed": metadata.get('date_filed'),
            "created": str(doc['created_at']),
            # NEW: Enhanced title fields
            "formatted_title": formatted_title,
            "formatted_title_short": formatted_title_short,
            "document_type_extracted": document_type_from_text,
            "citation_components": {
                "case_name": case_name,
                "document_type": document_type_from_text,
                "judge": metadata.get('judge_name'),
                "date_filed": metadata.get('date_filed'),
                "court": metadata.get('court_id')
            },
            # Enhanced XML parsing metadata (if available)
            "xml_metadata": {
                "parsing_enabled": metadata.get('xml_parsing_enabled', False),
                "judge_full": metadata.get('xml_judge_full'),
                "judge_name": metadata.get('xml_judge_name'),
                "opinion_type": metadata.get('xml_opinion_type'),
                "citation_count": metadata.get('xml_citation_count', 0),
                "paragraph_count": metadata.get('xml_paragraph_count', 0),
                "citations": metadata.get('xml_citations', []),
                "legal_motions": metadata.get('xml_legal_motions', []),
                "federal_rules": metadata.get('xml_federal_rules', []),
                "statutes": metadata.get('xml_statutes', []),
                "page_numbers": metadata.get('xml_page_numbers', [])
            } if metadata.get('xml_parsing_enabled') else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search")
async def search_simple(
    judge: Optional[str] = None,
    type: str = "all",
    min_length: int = 5000,
    limit: int = Query(default=10, le=200),  # Increased for bulk retrieval
    offset: int = Query(default=0, ge=0)
):
    """
    Simplified search - returns documents with direct text access
    Supports BULK retrieval for large-scale data export
    
    Usage:
    - /search?judge=Gilstrap&limit=100  # Get all Gilstrap docs
    - /search?type=020lead&limit=50
    - /search?judge=Albright&offset=10&limit=20  # Pagination
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query
        conditions = ["LENGTH(content) >= %s"]
        params = [min_length]
        
        if type and type != "all":
            conditions.append("document_type = %s")
            params.append(type)
            
        if judge:
            conditions.append("metadata->>'judge_name' ILIKE %s")
            params.append(f'%{judge}%')
        
        # First get total count for pagination
        count_query = f"""
            SELECT COUNT(*) as total
            FROM public.court_documents
            WHERE {' AND '.join(conditions)}
        """
        cur.execute(count_query, params.copy())
        total_count = cur.fetchone()['total']
        
        query = f"""
            SELECT 
                id,
                case_number,
                document_type,
                content,
                metadata,
                LENGTH(content) as raw_length
            FROM public.court_documents
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        cur.execute(query, params)
        documents = cur.fetchall()
        cur.close()
        conn.close()
        
        # Process with SIMPLE structure
        results = []
        for doc in documents:
            metadata = doc['metadata'] if isinstance(doc['metadata'], dict) else json.loads(doc['metadata'] or '{}')
            text = extract_plain_text(doc['content'])
            
            # Extract document type from text
            document_type_from_text = extract_document_type(text)
            
            # Get case name
            case_name = metadata.get('case_name') or doc['case_number'] or f"DOC-{doc['id']}"
            
            # Format enhanced titles
            formatted_title = format_legal_title(
                case_name=case_name,
                document_type=document_type_from_text,
                judge_name=metadata.get('judge_name'),
                date_filed=metadata.get('date_filed'),
                court_id=metadata.get('court_id')
            )
            
            formatted_title_short = format_legal_title(
                case_name=case_name,
                document_type=document_type_from_text,
                judge_name=metadata.get('judge_name'),
                date_filed=metadata.get('date_filed'),
                court_id=metadata.get('court_id'),
                short_form=True
            )
            
            results.append({
                "id": doc['id'],
                "case": doc['case_number'] or f"DOC-{doc['id']}",  # Keep for backwards compatibility
                "type": doc['document_type'],
                "judge": metadata.get('judge_name', 'Unknown'),
                "court": metadata.get('court_id', 'Unknown'),
                "date_filed": metadata.get('date_filed'),
                "text": text,  # Full text directly available
                "text_length": len(text),
                "preview": text[:500] + "..." if len(text) > 500 else text,
                # NEW: Enhanced title fields
                "formatted_title": formatted_title,
                "formatted_title_short": formatted_title_short,
                "document_type_extracted": document_type_from_text,
                # Include citation components for better formatting
                "citation_components": {
                    "case_name": case_name,
                    "document_type": document_type_from_text,
                    "judge": metadata.get('judge_name'),
                    "date_filed": metadata.get('date_filed'),
                    "court": metadata.get('court_id')
                }
            })
        
        return {
            "total": total_count,
            "returned": len(results),
            "offset": offset,
            "limit": limit,
            "documents": results
        }
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/es")
async def search_elasticsearch(
    query: str = Query(description="Search query for full-text search"),
    judge: Optional[str] = None,
    court: Optional[str] = None,
    document_type: Optional[str] = None,
    limit: int = Query(default=10, le=50),
    offset: int = Query(default=0, ge=0)
):
    """
    Elasticsearch-powered full-text search

    Leverages Elasticsearch index for fast, relevance-scored search across document content.
    Supports filtering by judge, court, and document type.
    Future-ready for transcript data integration.

    Usage:
    - /search/es?query=patent%20infringement&limit=10
    - /search/es?query=summary%20judgment&judge=Gilstrap
    - /search/es?query=motion%20to%20dismiss&court=txed&limit=20
    """
    try:
        es = get_es_client()

        # Build Elasticsearch query
        es_query = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["content^2", "case_name", "formatted_title", "preview"],
                            "type": "best_fields",
                            "fuzziness": "AUTO"
                        }
                    }
                ],
                "filter": []
            }
        }

        # Add optional filters
        if judge:
            es_query["bool"]["filter"].append({
                "match": {"judge_name": judge}
            })

        if court:
            es_query["bool"]["filter"].append({
                "match": {"court_id": court}
            })

        if document_type:
            es_query["bool"]["filter"].append({
                "match": {"document_type": document_type}
            })

        # Execute search
        search_body = {
            "query": es_query,
            "from": offset,
            "size": limit,
            "highlight": {
                "fields": {
                    "content": {
                        "fragment_size": 150,
                        "number_of_fragments": 2
                    }
                }
            },
            "sort": [
                "_score",
                {"synced_at": {"order": "desc"}}
            ]
        }

        response = es.search(
            index=ES_CONFIG['index'],
            body=search_body
        )

        # Process results
        results = []
        for hit in response['hits']['hits']:
            source = hit['_source']

            # Extract highlights for preview
            highlights = hit.get('highlight', {}).get('content', [])
            preview_text = ' ... '.join(highlights) if highlights else source.get('preview', '')

            results.append({
                "id": source['id'],
                "case": source.get('case_number', 'Unknown'),
                "type": source.get('document_type', 'unknown'),
                "judge": source.get('judge_name', 'Unknown'),
                "court": source.get('court_id', 'unknown'),
                "date_filed": source.get('filing_date') or source.get('decision_date') or source.get('document_date'),
                "text_length": source.get('content_length', 0),
                "preview": preview_text,
                "formatted_title": source.get('formatted_title', f"Document {source['id']}"),
                "formatted_title_short": source.get('formatted_title_short', source.get('case_name', f"Document {source['id']}")),
                "document_type_extracted": source.get('document_type_extracted'),
                "score": hit['_score'],  # Relevance score
                "citation_components": {
                    "case_name": source.get('case_name'),
                    "document_type": source.get('document_type_extracted'),
                    "judge": source.get('judge_name'),
                    "date_filed": source.get('filing_date') or source.get('decision_date'),
                    "court": source.get('court_id')
                }
            })

        return {
            "total": response['hits']['total']['value'] if isinstance(response['hits']['total'], dict) else response['hits']['total'],
            "returned": len(results),
            "offset": offset,
            "limit": limit,
            "query": query,
            "documents": results
        }

    except Exception as e:
        logger.error(f"Elasticsearch search failed: {e}")
        # Fallback to regular search if ES fails
        logger.info("Falling back to PostgreSQL search")
        return await search_simple(judge=judge, type=document_type, limit=limit, offset=offset)

@app.get("/search/ai")
async def search_ai_powered(
    query: str = Query(description="Search query for AI-powered search"),
    profile: str = Query(default="professional", description="Search profile: basic, professional, advanced, research, litigation"),
    legal_topics: Optional[str] = Query(default=None, description="Comma-separated legal topics to filter by"),
    courts: Optional[str] = Query(default=None, description="Comma-separated court IDs to filter by"),
    judges: Optional[str] = Query(default=None, description="Comma-separated judge names to filter by"),
    dispositions: Optional[str] = Query(default=None, description="Comma-separated case dispositions to filter by"),
    date_start: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD) for date range filter"),
    date_end: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD) for date range filter"),
    limit: int = Query(default=10, le=50),
    offset: int = Query(default=0, ge=0)
):
    """
    AI-Powered Legal Search with Modular Features

    This endpoint provides advanced search capabilities using AI and legal intelligence:

    **Search Profiles:**
    - `basic`: Simple keyword search (fastest)
    - `professional`: Hybrid search + legal filtering (recommended)
    - `advanced`: Full AI features including outcome prediction
    - `research`: Research-focused with citation analysis
    - `litigation`: Litigation support with judicial patterns

    **Legal Intelligence Features:**
    - Semantic similarity search using 384-dim embeddings
    - Legal topic extraction and filtering
    - Case disposition analysis
    - Judicial pattern recognition
    - Citation network analysis
    - Outcome prediction (advanced profiles)

    **Usage Examples:**
    - /search/ai?query=patent infringement&profile=professional
    - /search/ai?query=summary judgment&profile=research&courts=txed,cand
    - /search/ai?query=evidence&legal_topics=Evidence Law&judges=Gilstrap
    """
    try:
        # Get search configuration based on profile
        profile_configs = {
            "basic": SearchProfiles.basic(),
            "professional": SearchProfiles.professional(),
            "advanced": SearchProfiles.advanced(),
            "research": SearchProfiles.research_focused(),
            "litigation": SearchProfiles.litigation_support()
        }

        config = profile_configs.get(profile, SearchProfiles.professional())

        # Initialize AI search engine
        es = get_es_client()
        ai_engine = AISearchEngine(es, config)

        # Build filters from query parameters
        filters = {}

        if legal_topics:
            filters["legal_topics"] = [topic.strip() for topic in legal_topics.split(",")]

        if courts:
            filters["courts"] = [court.strip() for court in courts.split(",")]

        if judges:
            filters["judges"] = [judge.strip() for judge in judges.split(",")]

        if dispositions:
            filters["dispositions"] = [disp.strip() for disp in dispositions.split(",")]

        if date_start and date_end:
            filters["date_range"] = {"start": date_start, "end": date_end}

        # Perform AI-powered search
        results = await ai_engine.search(
            query=query,
            filters=filters if filters else None,
            limit=limit,
            offset=offset
        )

        # Add metadata about the search
        results["search_profile"] = profile
        results["ai_features_active"] = len(config.enabled_features)
        results["legal_filters_applied"] = len(filters)

        return results

    except Exception as e:
        logger.error(f"AI search failed: {e}")
        # Graceful fallback to basic ES search
        logger.info("Falling back to basic Elasticsearch search")
        return await search_elasticsearch(query=query, limit=limit, offset=offset)

@app.get("/search/features")
async def get_available_features():
    """
    Get information about available AI search features and profiles

    Returns details about search capabilities, feature descriptions,
    and recommended use cases for each profile.
    """
    return {
        "available_features": [
            {
                "name": feature.value,
                "description": {
                    "basic_search": "Traditional keyword search with BM25 relevance scoring",
                    "semantic_search": "Vector similarity search using 384-dimensional embeddings",
                    "hybrid_search": "Combined keyword + semantic search for optimal relevance",
                    "legal_filtering": "Filter by legal topics, courts, judges, and case outcomes",
                    "citation_analysis": "Citation network analysis and precedent discovery",
                    "judicial_patterns": "Judge-specific ruling patterns and preferences",
                    "outcome_prediction": "Predict case outcomes based on similar cases",
                    "smart_suggestions": "AI-powered query expansion and suggestions"
                }.get(feature.value, "Advanced legal AI feature")
            }
            for feature in SearchFeature
        ],
        "search_profiles": {
            "basic": {
                "description": "Simple keyword search - fastest performance",
                "features": ["basic_search"],
                "use_cases": ["Quick document lookup", "Basic research", "High-volume queries"],
                "performance": "Fastest"
            },
            "professional": {
                "description": "Hybrid search with legal filtering - recommended for most users",
                "features": ["hybrid_search", "legal_filtering", "smart_suggestions"],
                "use_cases": ["Legal research", "Case preparation", "Professional practice"],
                "performance": "Balanced"
            },
            "advanced": {
                "description": "Full AI capabilities including outcome prediction",
                "features": ["hybrid_search", "legal_filtering", "citation_analysis", "judicial_patterns", "outcome_prediction", "smart_suggestions"],
                "use_cases": ["Complex litigation", "Legal strategy", "Academic research"],
                "performance": "Comprehensive"
            },
            "research": {
                "description": "Research-focused with enhanced citation analysis",
                "features": ["hybrid_search", "legal_filtering", "citation_analysis"],
                "use_cases": ["Academic research", "Legal writing", "Precedent discovery"],
                "performance": "Research-optimized"
            },
            "litigation": {
                "description": "Litigation support with judicial insights",
                "features": ["hybrid_search", "legal_filtering", "judicial_patterns", "outcome_prediction"],
                "use_cases": ["Trial preparation", "Judge research", "Outcome modeling"],
                "performance": "Strategy-focused"
            }
        },
        "dataset_info": {
            "total_documents": await get_document_count(),
            "has_embeddings": True,
            "has_legal_topics": True,
            "has_case_dispositions": True,
            "courts_available": await get_court_count(),
            "judges_available": await get_judge_count()
        }
    }

async def get_document_count():
    """Helper to get total document count"""
    try:
        es = get_es_client()
        response = await es.count(index="court-documents")
        return response["count"]
    except:
        return 210  # Fallback

async def get_court_count():
    """Helper to get unique court count"""
    try:
        es = get_es_client()
        response = await es.search(
            index="court-documents",
            body={"size": 0, "aggs": {"courts": {"cardinality": {"field": "court_id.keyword"}}}}
        )
        return response["aggregations"]["courts"]["value"]
    except:
        return 10  # Fallback

async def get_judge_count():
    """Helper to get unique judge count"""
    try:
        es = get_es_client()
        response = await es.search(
            index="court-documents",
            body={"size": 0, "aggs": {"judges": {"cardinality": {"field": "judge_name.keyword"}}}}
        )
        return response["aggregations"]["judges"]["value"]
    except:
        return 20  # Fallback

@app.get("/list")
async def list_documents(
    type: str = "020lead",
    limit: int = Query(default=20, le=100)
):
    """
    Simple list of available documents with basic info
    
    Returns minimal info for browsing, use /text/{id} for full content
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                id,
                case_number,
                document_type,
                metadata,
                LENGTH(content) as size
            FROM public.court_documents
            WHERE document_type = %s
            AND LENGTH(content) > 1000
            ORDER BY created_at DESC
            LIMIT %s
        """
        
        cur.execute(query, (type, limit))
        documents = cur.fetchall()
        cur.close()
        conn.close()
        
        # Ultra-simple list format with enhanced titles
        results = []
        for doc in documents:
            metadata = doc['metadata'] if isinstance(doc['metadata'], dict) else json.loads(doc['metadata'] or '{}')
            
            # Get case name
            case_name = metadata.get('case_name') or doc['case_number'] or f"DOC-{doc['id']}"
            
            # For list view, we can't extract doc type without content, so use generic
            formatted_title_short = format_legal_title(
                case_name=case_name,
                document_type=None,  # We don't have content in list view
                judge_name=metadata.get('judge_name'),
                date_filed=metadata.get('date_filed'),
                court_id=metadata.get('court_id'),
                short_form=True
            )
            
            results.append({
                "id": doc['id'],
                "case": doc['case_number'] or f"DOC-{doc['id']}",  # Keep for backwards compatibility
                "judge": metadata.get('judge_name', 'Unknown'),
                "size": doc['size'],
                "text_url": f"/text/{doc['id']}",  # Direct link to text
                # NEW: Enhanced title field
                "formatted_title_short": formatted_title_short
            })
        
        return results
        
    except Exception as e:
        logger.error(f"List failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bulk/judge/{judge_name}")
async def get_bulk_by_judge(
    judge_name: str,
    type: str = "020lead",
    include_text: bool = Query(default=True, description="Include full text (set false for metadata only)")
):
    """
    Bulk retrieval of ALL documents for a specific judge
    Optimized for large-scale data export
    
    Usage:
    - /bulk/judge/Gilstrap - Get ALL Gilstrap documents with full text
    - /bulk/judge/Albright?include_text=false - Get metadata only for faster response
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query
        conditions = ["metadata->>'judge_name' ILIKE %s"]
        params = [f'%{judge_name}%']
        
        if type and type != "all":
            conditions.append("document_type = %s")
            params.append(type)
        
        query = f"""
            SELECT 
                id,
                case_number,
                document_type,
                content,
                metadata,
                LENGTH(content) as raw_length,
                created_at
            FROM public.court_documents
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
        """
        
        cur.execute(query, params)
        documents = cur.fetchall()
        cur.close()
        conn.close()
        
        # Process documents
        results = []
        total_text_chars = 0
        
        for doc in documents:
            metadata = doc['metadata'] if isinstance(doc['metadata'], dict) else json.loads(doc['metadata'] or '{}')
            
            doc_result = {
                "id": doc['id'],
                "case": doc['case_number'] or f"DOC-{doc['id']}",
                "type": doc['document_type'],
                "judge": metadata.get('judge_name', judge_name),
                "court": metadata.get('court_id', 'Unknown'),
                "date_filed": metadata.get('date_filed'),
                "created": str(doc['created_at']),
                # Always include XML metadata structure (unconditionally)
                "xml_metadata": {
                    "parsing_enabled": metadata.get('xml_parsing_enabled', False),
                    "judge_full": metadata.get('xml_judge_full'),
                    "judge_name": metadata.get('xml_judge_name'),
                    "opinion_type": metadata.get('xml_opinion_type'),
                    "citation_count": metadata.get('xml_citation_count', 0) if metadata.get('xml_parsing_enabled') else 0,
                    "paragraph_count": metadata.get('xml_paragraph_count', 0) if metadata.get('xml_parsing_enabled') else 0,
                    "citations": metadata.get('xml_citations', []) if metadata.get('xml_parsing_enabled') else [],
                    "legal_motions": metadata.get('xml_legal_motions', []) if metadata.get('xml_parsing_enabled') else [],
                    "federal_rules": metadata.get('xml_federal_rules', []) if metadata.get('xml_parsing_enabled') else [],
                    "statutes": metadata.get('xml_statutes', []) if metadata.get('xml_parsing_enabled') else [],
                    "page_numbers": metadata.get('xml_page_numbers', []) if metadata.get('xml_parsing_enabled') else []
                }
            }
            
            if include_text:
                text = extract_plain_text(doc['content'])
                doc_result["text"] = text
                doc_result["text_length"] = len(text)
                total_text_chars += len(text)
            else:
                doc_result["raw_length"] = doc['raw_length']
            
            results.append(doc_result)
        
        return {
            "judge": judge_name,
            "total_documents": len(results),
            "total_text_characters": total_text_chars if include_text else None,
            "documents": results
        }
        
    except Exception as e:
        logger.error(f"Bulk retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/judges")
async def list_available_judges(
    min_docs: int = Query(default=5, description="Minimum document count to include judge"),
    min_length: int = Query(default=5000, description="Minimum content length for substantial documents")
):
    """
    Get list of all available judges with document counts

    Returns judges who have substantial documents in the database.
    Useful for populating dynamic UI elements like Document Context cabinets.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Query to get judge statistics
        query = """
            SELECT
                metadata->>'judge_name' as judge_name,
                metadata->>'court_id' as court_id,
                COUNT(*) as total_documents,
                COUNT(CASE WHEN LENGTH(content) >= %s THEN 1 END) as substantial_documents,
                MAX(metadata->>'judge_name') as full_name,
                MIN(created_at) as first_document,
                MAX(created_at) as latest_document
            FROM public.court_documents
            WHERE metadata->>'judge_name' IS NOT NULL
            AND metadata->>'judge_name' != ''
            AND metadata->>'judge_name' != 'Unknown'
            AND LENGTH(content) > 1000
            GROUP BY metadata->>'judge_name', metadata->>'court_id'
            HAVING COUNT(*) >= %s
            AND COUNT(CASE WHEN LENGTH(content) >= %s THEN 1 END) >= %s
            ORDER BY substantial_documents DESC, total_documents DESC
        """

        cur.execute(query, [min_length, min_docs, min_length, min_docs])
        results = cur.fetchall()
        cur.close()
        conn.close()

        judges = []
        for row in results:
            # Extract short name (e.g., "Rodney Gilstrap" -> "Gilstrap")
            full_name = row['judge_name'] or row['full_name']
            short_name = full_name.split()[-1] if full_name else 'Unknown'

            judges.append({
                "name": short_name,
                "full_name": full_name,
                "court": row['court_id'] or 'Unknown',
                "total_documents": row['total_documents'],
                "substantial_documents": row['substantial_documents'],
                "first_document": row['first_document'].isoformat() if row['first_document'] else None,
                "latest_document": row['latest_document'].isoformat() if row['latest_document'] else None
            })

        return {
            "judges": judges,
            "total_judges": len(judges),
            "filters": {
                "min_documents": min_docs,
                "min_content_length": min_length
            }
        }

    except Exception as e:
        logger.error(f"Failed to list judges: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/courts")
async def list_available_courts(
    min_docs: int = Query(default=10, description="Minimum document count to include court")
):
    """
    Get list of all available courts with document counts

    Returns courts that have substantial document collections.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Query to get court statistics
        query = """
            SELECT
                metadata->>'court_id' as court_id,
                COUNT(*) as total_documents,
                COUNT(DISTINCT metadata->>'judge_name') as judge_count,
                COUNT(CASE WHEN LENGTH(content) >= 5000 THEN 1 END) as substantial_documents,
                MIN(created_at) as first_document,
                MAX(created_at) as latest_document
            FROM public.court_documents
            WHERE metadata->>'court_id' IS NOT NULL
            AND metadata->>'court_id' != ''
            AND metadata->>'court_id' != 'Unknown'
            GROUP BY metadata->>'court_id'
            HAVING COUNT(*) >= %s
            ORDER BY total_documents DESC
        """

        cur.execute(query, [min_docs])
        results = cur.fetchall()

        # Get court name mappings
        court_names = {
            'txed': 'Eastern District of Texas',
            'nysd': 'Southern District of New York',
            'dcd': 'District of Columbia',
            'ded': 'District of Delaware',
            'ilnd': 'Northern District of Illinois',
            'cit': 'Court of International Trade'
        }

        courts = []
        for row in results:
            court_id = row['court_id']
            court_name = court_names.get(court_id, court_id.upper() if court_id else 'Unknown Court')

            courts.append({
                "court_id": court_id,
                "name": court_name,
                "total_documents": row['total_documents'],
                "substantial_documents": row['substantial_documents'],
                "judge_count": row['judge_count'],
                "first_document": row['first_document'].isoformat() if row['first_document'] else None,
                "latest_document": row['latest_document'].isoformat() if row['latest_document'] else None
            })

        cur.close()
        conn.close()

        return {
            "courts": courts,
            "total_courts": len(courts),
            "filters": {
                "min_documents": min_docs
            }
        }

    except Exception as e:
        logger.error(f"Failed to list courts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/summary")
async def get_data_summary():
    """
    Get overview statistics of the document collection

    Provides high-level metrics useful for dashboards and data insights.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get overall statistics
        cur.execute("""
            SELECT
                COUNT(*) as total_documents,
                COUNT(CASE WHEN LENGTH(content) >= 5000 THEN 1 END) as substantial_documents,
                COUNT(CASE WHEN LENGTH(content) >= 50000 THEN 1 END) as very_long_documents,
                COUNT(DISTINCT metadata->>'judge_name') as unique_judges,
                COUNT(DISTINCT metadata->>'court_id') as unique_courts,
                SUM(LENGTH(content)) as total_characters,
                AVG(LENGTH(content))::int as avg_document_length
            FROM public.court_documents
            WHERE content IS NOT NULL
            AND content != ''
            AND metadata->>'judge_name' IS NOT NULL
            AND metadata->>'judge_name' != 'Unknown'
        """)

        stats = cur.fetchone()

        # Get top judges
        cur.execute("""
            SELECT metadata->>'judge_name' as judge_name, COUNT(*) as doc_count
            FROM public.court_documents
            WHERE metadata->>'judge_name' IS NOT NULL
            AND metadata->>'judge_name' != 'Unknown'
            AND LENGTH(content) >= 5000
            GROUP BY metadata->>'judge_name'
            ORDER BY COUNT(*) DESC
            LIMIT 5
        """)

        top_judges = [{"name": row['judge_name'], "documents": row['doc_count']}
                     for row in cur.fetchall()]

        # Get top courts
        cur.execute("""
            SELECT metadata->>'court_id' as court_id, COUNT(*) as doc_count
            FROM public.court_documents
            WHERE metadata->>'court_id' IS NOT NULL
            AND metadata->>'court_id' != 'Unknown'
            GROUP BY metadata->>'court_id'
            ORDER BY COUNT(*) DESC
            LIMIT 5
        """)

        top_courts = [{"court_id": row['court_id'], "documents": row['doc_count']}
                     for row in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "total_documents": stats['total_documents'],
            "substantial_documents": stats['substantial_documents'],
            "very_long_documents": stats['very_long_documents'],
            "unique_judges": stats['unique_judges'],
            "unique_courts": stats['unique_courts'],
            "total_characters": stats['total_characters'],
            "avg_document_length": stats['avg_document_length'],
            "top_judges": top_judges,
            "top_courts": top_courts,
            "data_quality": {
                "substantial_ratio": round(stats['substantial_documents'] / max(stats['total_documents'], 1), 3),
                "very_long_ratio": round(stats['very_long_documents'] / max(stats['total_documents'], 1), 3)
            }
        }

    except Exception as e:
        logger.error(f"Failed to get summary stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# LEGAL ANALYTICS ENDPOINTS - Optimized for RAG Consumption
# =============================================================================

@app.get("/analytics/related-cases/{document_id}")
async def get_related_cases(
    document_id: str,
    max_recommendations: int = Query(default=20, le=50, description="Maximum number of related cases to return"),
    min_score_threshold: float = Query(default=0.1, description="Minimum similarity score threshold"),
    include_full_graph: bool = Query(default=True, description="Include complete citation/topic graphs")
):
    """
    Get Related Cases for RAG Consumption

    Returns comprehensive case recommendations optimized for AI consumption:
    - Ranked similar cases with detailed scoring reasons
    - Citation network subgraphs
    - Topic cluster memberships
    - Authority rankings and metadata
    - Computational provenance for LLM reasoning

    **Algorithm:** Multi-signal similarity using citation overlap, topic similarity,
    judicial patterns, semantic embeddings, and authority scoring.

    **RAG Optimization:** Returns complete relational data structures that LLMs
    can use to understand case relationships and provide contextual recommendations.
    """
    try:
        es = get_es_client()
        related_service = RelatedCaseService(es)

        result = await related_service.get_related_cases(
            document_id=document_id,
            max_recommendations=max_recommendations,
            min_score_threshold=min_score_threshold,
            include_full_graph=include_full_graph
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Related cases analysis failed: {e}")
        raise HTTPException(status_code=500, detail="Related cases analysis failed")

@app.get("/analytics/topic-clusters")
async def get_topic_clusters(
    min_cluster_size: int = Query(default=5, description="Minimum documents per cluster"),
    max_clusters: int = Query(default=50, description="Maximum number of clusters"),
    similarity_threshold: float = Query(default=0.3, description="Topic similarity threshold"),
    use_semantic_clustering: bool = Query(default=True, description="Use semantic embeddings for clustering")
):
    """
    Get Legal Topic Clusters for RAG Consumption

    Returns comprehensive topic clustering optimized for AI consumption:
    - Hierarchical topic clusters with coherence scores
    - Document-cluster membership mappings
    - Topic similarity matrices
    - Cluster relationship graphs
    - Representative cases per cluster

    **Algorithm:** Combines co-occurrence analysis with semantic embeddings
    using agglomerative clustering and topic coherence optimization.

    **RAG Optimization:** Provides complete clustering metadata that LLMs
    can use to understand document organization and suggest topical research directions.
    """
    try:
        es = get_es_client()
        clustering_service = TopicClusteringService(es)

        result = await clustering_service.build_topic_clusters(
            min_cluster_size=min_cluster_size,
            max_clusters=max_clusters,
            similarity_threshold=similarity_threshold,
            use_semantic_clustering=use_semantic_clustering
        )

        return result

    except Exception as e:
        logger.error(f"Topic clustering failed: {e}")
        raise HTTPException(status_code=500, detail="Topic clustering analysis failed")

@app.get("/analytics/topic-clusters/{document_id}")
async def get_document_topic_clusters(document_id: str):
    """
    Get Topic Cluster Information for Specific Document

    Returns document-specific topic analysis including:
    - Primary topics with confidence scores
    - Topic distribution analysis
    - Suggested cluster memberships
    - Related documents in same clusters
    """
    try:
        es = get_es_client()
        clustering_service = TopicClusteringService(es)

        result = await clustering_service.get_document_topic_clusters(document_id)

        if not result:
            raise HTTPException(status_code=404, detail="Document not found")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document topic analysis failed: {e}")
        raise HTTPException(status_code=500, detail="Document topic analysis failed")

@app.get("/analytics/citation-network")
async def get_citation_network(
    force_rebuild: bool = Query(default=False, description="Force rebuild of citation network")
):
    """
    Get Citation Network Analysis for RAG Consumption

    Returns comprehensive citation analysis optimized for AI consumption:
    - Authority rankings for all cited entities (PageRank-based)
    - Citation relationship graphs (forward and backward)
    - Legal citation patterns and statistics
    - Network topology metrics
    - Computational metadata for provenance

    **Algorithm:** Uses PageRank for authority scoring, citation normalization,
    and network analysis for legal precedent identification.

    **RAG Optimization:** Provides complete citation authority data that LLMs
    can use to assess case importance and identify authoritative sources.
    """
    try:
        es = get_es_client()
        citation_service = CitationAnalyticsService(es)

        result = await citation_service.build_citation_network(force_rebuild=force_rebuild)

        return result

    except Exception as e:
        logger.error(f"Citation network analysis failed: {e}")
        raise HTTPException(status_code=500, detail="Citation network analysis failed")

@app.get("/analytics/citation-network/{document_id}")
async def get_document_citation_analysis(document_id: str):
    """
    Get Citation Analysis for Specific Document

    Returns document-specific citation analysis including:
    - Authority score and ranking
    - Outgoing citations (what this document cites)
    - Incoming citations (what cites this document)
    - Citation pattern analysis
    - Network position metrics
    """
    try:
        es = get_es_client()
        citation_service = CitationAnalyticsService(es)

        result = await citation_service.get_document_citation_analysis(document_id)

        if not result:
            raise HTTPException(status_code=404, detail="Document not found")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document citation analysis failed: {e}")
        raise HTTPException(status_code=500, detail="Document citation analysis failed")

@app.get("/analytics/statistics")
async def get_analytics_statistics():
    """
    Get Legal Analytics Statistics

    Returns comprehensive statistics for monitoring and debugging:
    - Related case service network metrics
    - Topic clustering statistics
    - Citation network statistics
    - Service health indicators
    """
    try:
        es = get_es_client()

        # Initialize services
        related_service = RelatedCaseService(es)
        clustering_service = TopicClusteringService(es)
        citation_service = CitationAnalyticsService(es)

        # Gather statistics
        stats = {
            "related_cases": await related_service.get_network_statistics(),
            "topic_clustering": await clustering_service.get_clustering_statistics(),
            "citation_network": await citation_service.get_citation_statistics(),
            "timestamp": datetime.now().isoformat()
        }

        return stats

    except Exception as e:
        logger.error(f"Analytics statistics failed: {e}")
        raise HTTPException(status_code=500, detail="Analytics statistics failed")

# =============================================================================

@app.get("/sample")
async def get_sample_text():
    """
    Get a sample of long-form content for testing
    
    Returns the first available 020lead document's text
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT content
            FROM public.court_documents
            WHERE document_type = '020lead'
            AND LENGTH(content) > 50000
            LIMIT 1
        """)
        
        doc = cur.fetchone()
        cur.close()
        conn.close()
        
        if not doc:
            return {"error": "No long-form documents available"}
        
        text = extract_plain_text(doc['content'])
        
        return {
            "text": text,
            "length": len(text),
            "preview": text[:1000]
        }
        
    except Exception as e:
        logger.error(f"Sample failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info(f"Starting Simplified Court Documents API on port {API_PORT}")
    logger.info(f"Database: {DB_CONFIG['database']} at {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    
    print("\n🚀 Simplified API Examples:")
    print(f"  Get text directly:     curl http://localhost:{API_PORT}/text/420")
    print(f"  Get as JSON:           curl http://localhost:{API_PORT}/documents/420")
    print(f"  Search Gilstrap:       curl http://localhost:{API_PORT}/search?judge=Gilstrap")
    print(f"  List documents:        curl http://localhost:{API_PORT}/list")
    print(f"  Get sample:            curl http://localhost:{API_PORT}/sample\n")
    
    # Run the API
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=API_PORT,
        log_level="info"
    )