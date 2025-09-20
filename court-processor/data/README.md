# Court Processor Sample Data

This directory contains a backup of 637 court documents for development and testing.

## Contents

- **court_documents_backup.sql.gz** - Compressed SQL backup (3.9MB compressed, 15MB uncompressed)
  - 637 court documents from public.court_documents table
  - 72 XML-enhanced documents with structured legal metadata
  - Document types: opinion, 020lead, opinion_doctor, published_opinion
  - Date range: 1996-05-02 to 2025-09-16
  - Enhanced features: citations, judge attribution, legal motions, federal rules

## Restoration

### Quick Restore (Recommended)
```bash
./dev db restore-court-data
```

### Manual Restore
```bash
# From project root
gunzip -c court-processor/data/court_documents_backup.sql.gz | \
  docker exec -i aletheia_development-db-1 psql -U aletheia -d aletheia
```

### Alternative Script
```bash
# From court-processor/data/
./restore_data.sh
```

## Data Statistics

- **Total Size**: ~15MB of text content
- **Average Document**: ~24KB
- **XML-Enhanced Docs**: 72 with structured metadata
- **Citation-Rich Docs**: 6 documents with 30+ citations
- **Top Courts**: cand (82), txed (72), ded (44)

## Integration with Setup

The `./dev up` command automatically restores this data when:
- Starting services for the first time (empty database)
- The backup file is present
- The database becomes ready

This ensures new users immediately have sample data available.

## Creating a New Backup

### Using Dev CLI (Recommended)

```bash
./dev db backup -b
# or
./dev db backup --update-baseline
```

This command will:
- Export current court documents from the database
- Update both backup files (this location and data/db-backups/)
- Maintain the same compression and format as the original
- Show XML enhancement statistics and file sizes

### Manual Method (Alternative)

```bash
# Export current data
docker exec aletheia_development-db-1 pg_dump -U aletheia -d aletheia \
  -t public.court_documents --data-only --inserts > \
  court-processor/data/court_documents_backup.sql

# Compress it
gzip -f court-processor/data/court_documents_backup.sql
```

## Notes

- This data is for development/testing only
- Contains public court opinions from CourtListener
- No sensitive or private information included