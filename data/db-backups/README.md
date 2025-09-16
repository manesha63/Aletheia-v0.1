# Court Documents Database Backup

This directory contains a compressed backup of the court documents (opinions) from the Aletheia database.

## Files

- `court_documents_complete.sql.gz` - Complete SQL dump of the court_documents table (3.9MB compressed)
- `restore_court_documents.sh` - Script to restore the backup

## Statistics

- **Total Documents**: 637 court opinions and related documents
- **XML-Enhanced**: 72 documents with structured legal metadata
- **Uncompressed Size**: ~15MB
- **Compressed Size**: 3.9MB (suitable for git storage)
- **Compression Ratio**: ~74% size reduction
- **Enhanced Features**: Citations, judge attribution, legal motions, federal rules

## Usage

### To Restore the Database

```bash
cd data/db-backups
./restore_court_documents.sh
```

The restore script will:
1. Decompress the backup file
2. Detect if running in Docker or locally
3. Restore the court_documents table
4. Verify the number of documents restored

### Manual Restore (Alternative)

```bash
# Decompress
gunzip -k court_documents_complete.sql.gz

# Restore via Docker
docker exec -i aletheia_development-db-1 psql -U aletheia -d aletheia < court_documents_complete.sql

# Or restore to local PostgreSQL
psql -h localhost -p 8200 -U aletheia -d aletheia -f court_documents_complete.sql
```

## Creating a Fresh Backup

### Using Dev CLI (Recommended)

```bash
./dev db backup -b
# or
./dev db backup --update-baseline
```

This command will:
- Export current court documents from the database
- Compress using maximum compression (gzip -9)
- Update both backup files (data/db-backups/ and court-processor/data/)
- Show statistics including XML-enhanced document count
- Provide guidance for committing updated backups

### Manual Method (Alternative)

```bash
# Export data
docker exec aletheia_development-db-1 pg_dump -U aletheia -d aletheia -t court_documents > court_documents_complete.sql

# Compress
gzip -9 court_documents_complete.sql
```

## Notes

- This backup includes both the table schema and all data
- The backup uses INSERT statements for maximum compatibility
- Safe to commit to git due to small compressed size (3.1MB)