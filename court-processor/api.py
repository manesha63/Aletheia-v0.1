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
import uvicorn
import logging

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