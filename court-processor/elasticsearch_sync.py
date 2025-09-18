#!/usr/bin/env python3
"""
Direct PostgreSQL → Elasticsearch Sync Service
===============================================

Replaces Haystack middleware with direct integration.
Syncs court documents from PostgreSQL to Elasticsearch with vector embeddings.

Key Features:
- Direct Elasticsearch client integration
- Automatic embedding generation using sentence-transformers
- Bulk indexing for performance
- Incremental sync support
- Comprehensive error handling and logging
"""

import os
import sys
import logging
import traceback
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
import json

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch, helpers
from sentence_transformers import SentenceTransformer
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ElasticsearchSync:
    """Direct PostgreSQL to Elasticsearch synchronization service"""

    def __init__(self):
        """Initialize the sync service with database and Elasticsearch connections"""

        # Configuration from environment
        self.db_config = {
            'host': os.getenv('DB_HOST', 'db' if os.path.exists('/.dockerenv') else 'localhost'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'aletheia'),
            'user': os.getenv('DB_USER', 'aletheia'),
            'password': os.getenv('DB_PASSWORD', 'aletheia123')
        }

        self.es_host = os.getenv('ELASTICSEARCH_HOST', 'http://localhost:9200')
        self.es_index = os.getenv('ELASTICSEARCH_INDEX', 'court-documents')
        self.embedding_model_name = os.getenv('EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')

        # Initialize connections
        self.db_conn = None
        self.es_client = None
        self.embedding_model = None

        # Sync statistics
        self.stats = {
            'total_documents': 0,
            'synced_documents': 0,
            'failed_documents': 0,
            'embeddings_generated': 0,
            'errors': []
        }

    def connect(self) -> bool:
        """Establish connections to PostgreSQL, Elasticsearch, and load embedding model"""
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

            # Load embedding model
            logger.info(f"Loading embedding model: {self.embedding_model_name}")
            self.embedding_model = SentenceTransformer(self.embedding_model_name)
            logger.info("✅ Embedding model loaded")

            return True

        except Exception as e:
            logger.error(f"❌ Connection failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def create_index(self) -> bool:
        """Create Elasticsearch index with proper mapping for court documents"""
        try:
            # Check if index already exists
            if self.es_client.indices.exists(index=self.es_index):
                logger.info(f"Index '{self.es_index}' already exists")
                return True

            # Define mapping optimized for legal documents
            mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "analyzer": {
                            "legal_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": [
                                    "lowercase",
                                    "stop",
                                    "snowball"
                                ]
                            }
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "id": {
                            "type": "integer"
                        },
                        "case_number": {
                            "type": "keyword",
                            "fields": {
                                "text": {
                                    "type": "text",
                                    "analyzer": "legal_analyzer"
                                }
                            }
                        },
                        "case_name": {
                            "type": "text",
                            "analyzer": "legal_analyzer",
                            "fields": {
                                "keyword": {
                                    "type": "keyword"
                                }
                            }
                        },
                        "document_type": {
                            "type": "keyword"
                        },
                        "content": {
                            "type": "text",
                            "analyzer": "legal_analyzer"
                        },
                        "content_embedding": {
                            "type": "dense_vector",
                            "dims": 384,
                            "index": True,
                            "similarity": "cosine"
                        },
                        "metadata": {
                            "type": "object",
                            "dynamic": True
                        },
                        "file_path": {
                            "type": "keyword"
                        },
                        "processed": {
                            "type": "boolean"
                        },
                        "created_at": {
                            "type": "date"
                        },
                        "updated_at": {
                            "type": "date"
                        },
                        "synced_at": {
                            "type": "date"
                        },
                        "filing_date": {
                            "type": "date"
                        },
                        "decision_date": {
                            "type": "date"
                        },
                        "document_date": {
                            "type": "date"
                        },
                        "judge_name": {
                            "type": "keyword",
                            "fields": {
                                "text": {
                                    "type": "text",
                                    "analyzer": "legal_analyzer"
                                }
                            }
                        },
                        "court_id": {
                            "type": "keyword"
                        }
                    }
                }
            }

            # Create index
            logger.info(f"Creating index '{self.es_index}' with legal document mapping")
            self.es_client.indices.create(index=self.es_index, body=mapping)
            logger.info("✅ Index created successfully")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to create index: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_documents_from_postgres(self, limit: Optional[int] = None,
                                  offset: int = 0,
                                  incremental: bool = False) -> List[Dict[str, Any]]:
        """Fetch court documents from PostgreSQL"""
        try:
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)

            # Build query - only sync documents with actual content
            query = """
                SELECT id, case_number, case_name, document_type, file_path,
                       content, metadata, processed, created_at, updated_at
                FROM court_documents
                WHERE content IS NOT NULL AND content != ''
            """

            params = []

            # Add incremental filter if needed
            if incremental:
                # TODO: Implement incremental sync based on last sync timestamp
                query += " AND updated_at > %s"
                # For now, we'll implement this in a future version
                pass

            # Add ordering and limits
            query += " ORDER BY id"

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            if offset > 0:
                query += " OFFSET %s"
                params.append(offset)

            logger.info(f"Fetching documents from PostgreSQL (limit: {limit}, offset: {offset})")
            cursor.execute(query, params)

            documents = cursor.fetchall()
            self.stats['total_documents'] = len(documents)

            logger.info(f"✅ Fetched {len(documents)} documents from PostgreSQL")

            cursor.close()
            return [dict(doc) for doc in documents]

        except Exception as e:
            logger.error(f"❌ Failed to fetch documents from PostgreSQL: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for given text"""
        try:
            if not text or not text.strip():
                return None

            # Truncate very long documents to avoid memory issues
            max_length = 5000  # Adjust based on model limits
            if len(text) > max_length:
                text = text[:max_length]

            embedding = self.embedding_model.encode(text)
            self.stats['embeddings_generated'] += 1

            return embedding.tolist()

        except Exception as e:
            logger.warning(f"Failed to generate embedding: {str(e)}")
            return None

    def prepare_document_for_elasticsearch(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare a PostgreSQL document for Elasticsearch indexing"""
        try:
            # Generate embedding for content
            content = doc.get('content', '')
            content_embedding = None

            if content and content.strip():
                content_embedding = self.generate_embedding(content)

            # Extract metadata for enhanced fields
            metadata = doc.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            # Prepare Elasticsearch document
            es_doc = {
                'id': doc['id'],
                'case_number': doc.get('case_number'),
                'case_name': doc.get('case_name'),
                'document_type': doc.get('document_type'),
                'content': content,
                'file_path': doc.get('file_path'),
                'processed': doc.get('processed', False),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
                'synced_at': datetime.now(timezone.utc),
                'metadata': metadata,
                # Enhanced fields from metadata
                'judge_name': metadata.get('judge_name'),
                'court_id': metadata.get('court_id'),
                'filing_date': metadata.get('filing_date'),
                'decision_date': metadata.get('decision_date'),
                'document_date': metadata.get('document_date')
            }

            # Add embedding if generated successfully
            if content_embedding:
                es_doc['content_embedding'] = content_embedding

            return es_doc

        except Exception as e:
            logger.error(f"❌ Failed to prepare document {doc.get('id')}: {str(e)}")
            self.stats['errors'].append(f"Document {doc.get('id')}: {str(e)}")
            return None

    def bulk_index_documents(self, documents: List[Dict[str, Any]]) -> bool:
        """Bulk index documents to Elasticsearch"""
        try:
            if not documents:
                logger.warning("No documents to index")
                return True

            # Prepare bulk actions
            actions = []
            for doc in documents:
                es_doc = self.prepare_document_for_elasticsearch(doc)
                if es_doc:
                    action = {
                        '_index': self.es_index,
                        '_id': es_doc['id'],
                        '_source': es_doc
                    }
                    actions.append(action)

            if not actions:
                logger.warning("No valid documents to index")
                return False

            # Perform bulk indexing
            logger.info(f"Bulk indexing {len(actions)} documents to Elasticsearch")

            success_count, failed_items = helpers.bulk(
                self.es_client,
                actions,
                index=self.es_index,
                chunk_size=100,  # Process in chunks
                request_timeout=60
            )

            self.stats['synced_documents'] += success_count

            if failed_items:
                self.stats['failed_documents'] += len(failed_items)
                logger.error(f"❌ {len(failed_items)} documents failed to index")
                for item in failed_items:
                    self.stats['errors'].append(f"Failed to index: {item}")

            logger.info(f"✅ Successfully indexed {success_count} documents")

            return len(failed_items) == 0

        except Exception as e:
            logger.error(f"❌ Bulk indexing failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def sync_all_documents(self, batch_size: int = 100) -> bool:
        """Sync all documents from PostgreSQL to Elasticsearch"""
        try:
            logger.info("🚀 Starting full document synchronization")

            # Reset stats
            self.stats = {
                'total_documents': 0,
                'synced_documents': 0,
                'failed_documents': 0,
                'embeddings_generated': 0,
                'errors': []
            }

            offset = 0
            total_processed = 0

            while True:
                # Fetch batch of documents
                documents = self.get_documents_from_postgres(
                    limit=batch_size,
                    offset=offset
                )

                if not documents:
                    break

                # Index batch
                success = self.bulk_index_documents(documents)
                if not success:
                    logger.warning(f"Some documents in batch {offset}-{offset+len(documents)} failed to index")

                total_processed += len(documents)
                offset += batch_size

                logger.info(f"Processed {total_processed} documents so far...")

                # Break if we got fewer documents than requested (end of data)
                if len(documents) < batch_size:
                    break

            self.print_sync_summary()
            return self.stats['failed_documents'] == 0

        except Exception as e:
            logger.error(f"❌ Full sync failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_sync_status(self) -> Dict[str, Any]:
        """Get current synchronization status"""
        try:
            # Get PostgreSQL count
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM court_documents")
            pg_count = cursor.fetchone()[0]
            cursor.close()

            # Get Elasticsearch count
            es_count = 0
            if self.es_client.indices.exists(index=self.es_index):
                result = self.es_client.count(index=self.es_index)
                es_count = result.get('count', 0)

            return {
                'postgresql_documents': pg_count,
                'elasticsearch_documents': es_count,
                'sync_difference': pg_count - es_count,
                'index_exists': self.es_client.indices.exists(index=self.es_index),
                'last_sync_stats': self.stats
            }

        except Exception as e:
            logger.error(f"❌ Failed to get sync status: {str(e)}")
            return {'error': str(e)}

    def print_sync_summary(self):
        """Print a summary of the sync operation"""
        logger.info("\n" + "="*60)
        logger.info("SYNC SUMMARY")
        logger.info("="*60)
        logger.info(f"Total documents processed: {self.stats['total_documents']}")
        logger.info(f"Successfully synced: {self.stats['synced_documents']}")
        logger.info(f"Failed to sync: {self.stats['failed_documents']}")
        logger.info(f"Embeddings generated: {self.stats['embeddings_generated']}")

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
    """Main entry point for the sync service"""
    import argparse

    parser = argparse.ArgumentParser(description='PostgreSQL to Elasticsearch sync service')
    parser.add_argument('--create-index', action='store_true',
                       help='Create Elasticsearch index with proper mapping')
    parser.add_argument('--sync-all', action='store_true',
                       help='Sync all documents from PostgreSQL to Elasticsearch')
    parser.add_argument('--status', action='store_true',
                       help='Show sync status')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for document processing (default: 100)')

    args = parser.parse_args()

    # Initialize sync service
    sync_service = ElasticsearchSync()

    try:
        # Connect to services
        if not sync_service.connect():
            logger.error("Failed to connect to required services")
            sys.exit(1)

        # Execute requested operation
        if args.create_index:
            if sync_service.create_index():
                logger.info("✅ Index creation completed")
            else:
                logger.error("❌ Index creation failed")
                sys.exit(1)

        elif args.sync_all:
            if sync_service.sync_all_documents(batch_size=args.batch_size):
                logger.info("✅ Full sync completed successfully")
            else:
                logger.error("❌ Full sync completed with errors")
                sys.exit(1)

        elif args.status:
            status = sync_service.get_sync_status()
            print("\nSync Status:")
            print(json.dumps(status, indent=2, default=str))

        else:
            parser.print_help()

    finally:
        sync_service.close()


if __name__ == '__main__':
    main()