#!/usr/bin/env python3
"""
Enhanced Metadata Extractor for Court Documents
===============================================

Extracts judge names and court identifiers from document content and updates both
PostgreSQL metadata and Elasticsearch index with enhanced information.

Addresses GitHub Issues #189 and #190:
- Judge name extraction from multiple sources
- Court identifier extraction and standardization
"""

import os
import sys
import logging
import traceback
import re
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch

# Import existing extractors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from extractors.judge import ComprehensiveJudgeExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CourtIdentifierExtractor:
    """Extract and standardize court identifiers from case numbers and content"""

    # Common court identifier patterns in case numbers
    COURT_PATTERNS = {
        # Eastern District of Texas patterns
        r'2:\d+-cv-\d+-JRG': 'txed',
        r'2:\d+-cv-\d+-RSP': 'txed',
        r'2:\d+-cv-\d+-RWS': 'txed',
        r'Case No\. 2:\d+-cv-\d+': 'txed',

        # Delaware District patterns
        r'Civil Action No\. \d+-\d+-CFC': 'ded',
        r'C\.A\. No\. \d+-\d+': 'ded',
        r'Civ\. No\. \d+-\d+-CFC': 'ded',

        # General federal district patterns
        r'\d:\d+-cv-\d+': 'federal_district',
        r'\d:\d+-cr-\d+': 'federal_district',
    }

    # Court name mappings - based on actual document content analysis
    COURT_NAME_MAPPINGS = {
        # Full court names from opinions
        'United States District Court for the Eastern District of Texas': 'txed',
        'United States District Court for the District of Delaware': 'ded',
        'United States District Court for the Southern District of New York': 'nysd',
        'United States District Court for the Northern District of Illinois': 'ilnd',
        'United States District Court for the District of Columbia': 'dcd',
        'Court of International Trade': 'cit',

        # Short forms from docket entries
        'Eastern District of Texas': 'txed',
        'District of Delaware': 'ded',
        'Southern District of New York': 'nysd',
        'Northern District of Illinois': 'ilnd',
        'District of Columbia': 'dcd',

        # Header forms from opinions
        'FOR THE DISTRICT OF DELAWARE': 'ded',
        'FOR THE EASTERN DISTRICT OF TEXAS': 'txed',
        'FOR THE SOUTHERN DISTRICT OF NEW YORK': 'nysd',
        'FOR THE NORTHERN DISTRICT OF ILLINOIS': 'ilnd',
        'FOR THE DISTRICT OF COLUMBIA': 'dcd',

        # Abbreviations
        'E.D. Texas': 'txed',
        'D. Delaware': 'ded',
        'S.D. New York': 'nysd',
        'N.D. Illinois': 'ilnd',
        'D.D.C.': 'dcd',
    }

    @classmethod
    def extract_court_from_case_number(cls, case_number: str) -> Optional[str]:
        """Extract court identifier from case number pattern"""
        if not case_number:
            return None

        for pattern, court_id in cls.COURT_PATTERNS.items():
            if re.search(pattern, case_number, re.IGNORECASE):
                return court_id

        return None

    @classmethod
    def extract_court_from_content(cls, content: str) -> Optional[str]:
        """Extract court identifier from document content"""
        if not content:
            return None

        # Look for court mentions in first 2000 characters
        content_start = content[:2000]

        for court_name, court_id in cls.COURT_NAME_MAPPINGS.items():
            if court_name.lower() in content_start.lower():
                return court_id

        return None

    @classmethod
    def extract_comprehensive_court_info(cls, case_number: str = None,
                                       content: str = None,
                                       existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract court information from all available sources"""

        # Check existing metadata first
        if existing_metadata and existing_metadata.get('court_id'):
            return {
                'court_id': existing_metadata['court_id'],
                'source': 'existing_metadata',
                'confidence': 1.0
            }

        # Try case number pattern first (most reliable)
        if case_number:
            court_from_case = cls.extract_court_from_case_number(case_number)
            if court_from_case and court_from_case != 'federal_district':
                return {
                    'court_id': court_from_case,
                    'source': 'case_number_pattern',
                    'confidence': 0.9
                }

        # Try content extraction
        if content:
            court_from_content = cls.extract_court_from_content(content)
            if court_from_content:
                return {
                    'court_id': court_from_content,
                    'source': 'content_analysis',
                    'confidence': 0.7
                }

        # Fallback to generic federal if we found federal pattern
        if case_number:
            court_from_case = cls.extract_court_from_case_number(case_number)
            if court_from_case == 'federal_district':
                return {
                    'court_id': 'federal_district',
                    'source': 'case_number_generic',
                    'confidence': 0.5
                }

        return None


class JudgeContentExtractor:
    """Extract judge names directly from document content"""

    # Judge name patterns in content - based on actual document analysis
    JUDGE_PATTERNS = [
        # XML author tags in published opinions: <author>RODNEY GILSTRAP, UNITED STATES DISTRICT JUDGE</author>
        r'<author[^>]*>([^<]+?)(?:,\s*UNITED STATES DISTRICT JUDGE|,\s*U\.S\. DISTRICT JUDGE|,\s*DISTRICT JUDGE)[^<]*</author>',

        # Plain text patterns: "WILLIAMS, U.S. District Judge:"
        r'([A-Z][A-Za-z\s\.]+),\s+(?:UNITED STATES DISTRICT JUDGE|U\.S\. DISTRICT JUDGE|DISTRICT JUDGE)',

        # Before patterns: "Before: M. Miller Baker, Judge"
        r'(?:Before:\s+)([A-Z][A-Za-z\s\.]+),\s+Judge',

        # Docket pattern: "Judge: Rodney Gilstrap" (with actual name, not empty)
        r'Judge:\s+([A-Z][A-Za-z\s\.]{5,40})(?:\s*\n|\s*$)',

        # Assigned judge pattern
        r'(?:Assigned Judge:\s+)([A-Z][A-Za-z\s\.]{5,40})(?:\s*\n|\s*$)',
    ]

    @classmethod
    def extract_judge_from_content(cls, content: str) -> Optional[str]:
        """Extract judge name from document content"""
        if not content:
            return None

        # Search in first 3000 characters where judge info is usually located
        content_start = content[:3000]

        for pattern in cls.JUDGE_PATTERNS:
            matches = re.findall(pattern, content_start, re.IGNORECASE)
            if matches:
                judge_name = matches[0].strip()
                # Clean up the judge name
                judge_name = re.sub(r',?\s*(?:UNITED STATES DISTRICT JUDGE|U\.S\. DISTRICT JUDGE|DISTRICT JUDGE).*$', '', judge_name, flags=re.IGNORECASE)
                judge_name = judge_name.strip().rstrip(',.')

                # Validate it's actually a judge name
                invalid_patterns = ['nature of', 'cause:', 'filed:', 'court:', 'docket:', 'case:', 'unassigned', 'assigned']
                if any(invalid.lower() in judge_name.lower() for invalid in invalid_patterns):
                    continue

                # Must contain letters and look like a name (not all numbers or symbols)
                if not re.search(r'[A-Za-z]', judge_name) or len(judge_name.split()) < 2:
                    continue

                if len(judge_name) > 3 and len(judge_name) < 50:  # Reasonable name length
                    return judge_name

        return None


class MetadataEnhancer:
    """Main service for enhancing document metadata"""

    def __init__(self):
        """Initialize the enhancer with database and Elasticsearch connections"""

        # Configuration from environment
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '8200')),  # Use the external port
            'database': os.getenv('DB_NAME', 'aletheia'),
            'user': os.getenv('DB_USER', 'aletheia'),
            'password': os.getenv('DB_PASSWORD', 'DzpmbGc2FoLDlHLnuz_nGZkmjW0G1Ofq')
        }

        self.es_host = os.getenv('ELASTICSEARCH_HOST', 'http://localhost:9200')
        self.es_index = os.getenv('ELASTICSEARCH_INDEX', 'court-documents')

        # Initialize connections
        self.db_conn = None
        self.es_client = None

        # Enhancement statistics
        self.stats = {
            'documents_processed': 0,
            'judges_extracted': 0,
            'courts_extracted': 0,
            'metadata_updates': 0,
            'elasticsearch_updates': 0,
            'errors': []
        }

    def connect(self) -> bool:
        """Establish connections to PostgreSQL and Elasticsearch"""
        try:
            # Connect to PostgreSQL
            logger.info(f"Connecting to PostgreSQL at {self.db_config['host']}:{self.db_config['port']}")
            self.db_conn = psycopg2.connect(**self.db_config)
            logger.info("✅ PostgreSQL connection established")

            # Connect to Elasticsearch
            logger.info(f"Connecting to Elasticsearch at {self.es_host}")
            self.es_client = Elasticsearch([self.es_host])

            # Test Elasticsearch connection
            if not self.es_client.ping():
                raise Exception("Elasticsearch ping failed")
            logger.info("✅ Elasticsearch connection established")

            return True

        except Exception as e:
            logger.error(f"❌ Connection failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_documents_needing_enhancement(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get documents that need judge or court metadata enhancement"""
        try:
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)

            # Find documents missing judge or court information
            query = """
                SELECT id, case_number, case_name, document_type, content, metadata
                FROM court_documents
                WHERE content IS NOT NULL AND content != ''
                AND (
                    metadata IS NULL
                    OR metadata->>'judge_name' IS NULL
                    OR metadata->>'court_id' IS NULL
                )
                ORDER BY id
            """

            if limit:
                query += f" LIMIT {limit}"

            cursor.execute(query)
            documents = cursor.fetchall()

            logger.info(f"Found {len(documents)} documents needing enhancement")
            cursor.close()

            return [dict(doc) for doc in documents]

        except Exception as e:
            logger.error(f"❌ Failed to fetch documents: {str(e)}")
            return []

    def enhance_document_metadata(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and enhance metadata for a single document"""
        try:
            doc_id = doc['id']
            case_number = doc.get('case_number')
            content = doc.get('content', '')
            existing_metadata = doc.get('metadata', {})

            if isinstance(existing_metadata, str):
                try:
                    existing_metadata = json.loads(existing_metadata)
                except:
                    existing_metadata = {}

            enhanced_metadata = existing_metadata.copy()
            extraction_sources = {}

            # Extract judge information if missing
            if not enhanced_metadata.get('judge_name'):
                # Try existing comprehensive extractor first (for docket/API data)
                judge_info = ComprehensiveJudgeExtractor.extract_comprehensive_judge_info(
                    docket_number=case_number
                )

                if judge_info:
                    enhanced_metadata['judge_name'] = judge_info.name
                    extraction_sources['judge_source'] = judge_info.source
                    extraction_sources['judge_confidence'] = judge_info.confidence
                    self.stats['judges_extracted'] += 1
                else:
                    # Try content-based extraction
                    judge_from_content = JudgeContentExtractor.extract_judge_from_content(content)
                    if judge_from_content:
                        enhanced_metadata['judge_name'] = judge_from_content
                        extraction_sources['judge_source'] = 'content_extraction'
                        extraction_sources['judge_confidence'] = 0.8
                        self.stats['judges_extracted'] += 1

            # Extract court information if missing
            if not enhanced_metadata.get('court_id'):
                court_info = CourtIdentifierExtractor.extract_comprehensive_court_info(
                    case_number=case_number,
                    content=content,
                    existing_metadata=existing_metadata
                )

                if court_info:
                    enhanced_metadata['court_id'] = court_info['court_id']
                    extraction_sources['court_source'] = court_info['source']
                    extraction_sources['court_confidence'] = court_info['confidence']
                    self.stats['courts_extracted'] += 1

            # Add extraction metadata
            if extraction_sources:
                enhanced_metadata['enhancement_info'] = {
                    'enhanced_at': datetime.now(timezone.utc).isoformat(),
                    'sources': extraction_sources
                }

            return enhanced_metadata

        except Exception as e:
            logger.error(f"❌ Failed to enhance document {doc.get('id')}: {str(e)}")
            self.stats['errors'].append(f"Document {doc.get('id')}: {str(e)}")
            return existing_metadata

    def update_database_metadata(self, doc_id: int, enhanced_metadata: Dict[str, Any]) -> bool:
        """Update document metadata in PostgreSQL"""
        try:
            cursor = self.db_conn.cursor()

            update_query = """
                UPDATE court_documents
                SET metadata = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """

            cursor.execute(update_query, (json.dumps(enhanced_metadata), doc_id))
            self.db_conn.commit()
            cursor.close()

            self.stats['metadata_updates'] += 1
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update database for document {doc_id}: {str(e)}")
            return False

    def update_elasticsearch_document(self, doc_id: int, enhanced_metadata: Dict[str, Any]) -> bool:
        """Update document in Elasticsearch with enhanced metadata"""
        try:
            if not self.es_client.exists(index=self.es_index, id=doc_id):
                logger.warning(f"Document {doc_id} not found in Elasticsearch")
                return False

            # Update with new metadata fields
            update_body = {
                'doc': {
                    'judge_name': enhanced_metadata.get('judge_name'),
                    'court_id': enhanced_metadata.get('court_id'),
                    'enhanced_at': datetime.now(timezone.utc)
                }
            }

            # Remove None values
            update_body['doc'] = {k: v for k, v in update_body['doc'].items() if v is not None}

            self.es_client.update(
                index=self.es_index,
                id=doc_id,
                body=update_body
            )

            self.stats['elasticsearch_updates'] += 1
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update Elasticsearch for document {doc_id}: {str(e)}")
            return False

    def enhance_all_documents(self, batch_size: int = 50, limit: Optional[int] = None) -> bool:
        """Enhance metadata for all documents needing enhancement"""
        try:
            logger.info("🚀 Starting metadata enhancement")

            # Reset stats
            self.stats = {
                'documents_processed': 0,
                'judges_extracted': 0,
                'courts_extracted': 0,
                'metadata_updates': 0,
                'elasticsearch_updates': 0,
                'errors': []
            }

            # Get documents needing enhancement
            documents = self.get_documents_needing_enhancement(limit=limit)

            if not documents:
                logger.info("✅ No documents need enhancement")
                return True

            logger.info(f"📄 Processing {len(documents)} documents")

            for i, doc in enumerate(documents):
                doc_id = doc['id']

                try:
                    # Enhance metadata
                    enhanced_metadata = self.enhance_document_metadata(doc)

                    # Update database
                    db_success = self.update_database_metadata(doc_id, enhanced_metadata)

                    # Update Elasticsearch if document exists there
                    es_success = self.update_elasticsearch_document(doc_id, enhanced_metadata)

                    self.stats['documents_processed'] += 1

                    if (i + 1) % 10 == 0:
                        logger.info(f"Processed {i + 1}/{len(documents)} documents...")

                except Exception as e:
                    logger.error(f"❌ Failed to process document {doc_id}: {str(e)}")
                    self.stats['errors'].append(f"Document {doc_id}: {str(e)}")

            self.print_enhancement_summary()
            return len(self.stats['errors']) == 0

        except Exception as e:
            logger.error(f"❌ Enhancement failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def print_enhancement_summary(self):
        """Print a summary of the enhancement operation"""
        logger.info("\n" + "="*60)
        logger.info("METADATA ENHANCEMENT SUMMARY")
        logger.info("="*60)
        logger.info(f"Documents processed: {self.stats['documents_processed']}")
        logger.info(f"Judges extracted: {self.stats['judges_extracted']}")
        logger.info(f"Courts extracted: {self.stats['courts_extracted']}")
        logger.info(f"Database updates: {self.stats['metadata_updates']}")
        logger.info(f"Elasticsearch updates: {self.stats['elasticsearch_updates']}")

        if self.stats['errors']:
            logger.error(f"Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:  # Show first 5 errors
                logger.error(f"  - {error}")
            if len(self.stats['errors']) > 5:
                logger.error(f"  ... and {len(self.stats['errors']) - 5} more errors")

        logger.info("="*60)

    def close(self):
        """Close all connections"""
        try:
            if self.db_conn:
                self.db_conn.close()
                logger.info("PostgreSQL connection closed")

            if self.es_client:
                logger.info("Elasticsearch client closed")

        except Exception as e:
            logger.error(f"Error closing connections: {str(e)}")


def main():
    """Main entry point for the metadata enhancer"""
    import argparse

    parser = argparse.ArgumentParser(description='Enhance document metadata with judge and court information')
    parser.add_argument('--enhance-all', action='store_true',
                       help='Enhance all documents missing metadata')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Batch size for processing (default: 50)')
    parser.add_argument('--limit', type=int,
                       help='Limit number of documents to process (for testing)')
    parser.add_argument('--test', action='store_true',
                       help='Test mode - process only 5 documents')

    args = parser.parse_args()

    # Initialize enhancer
    enhancer = MetadataEnhancer()

    try:
        # Connect to services
        if not enhancer.connect():
            logger.error("Failed to connect to required services")
            sys.exit(1)

        # Execute enhancement
        if args.enhance_all or args.test:
            limit = 5 if args.test else args.limit
            if enhancer.enhance_all_documents(batch_size=args.batch_size, limit=limit):
                logger.info("✅ Enhancement completed successfully")
            else:
                logger.error("❌ Enhancement completed with errors")
                sys.exit(1)
        else:
            parser.print_help()

    finally:
        enhancer.close()


if __name__ == '__main__':
    main()