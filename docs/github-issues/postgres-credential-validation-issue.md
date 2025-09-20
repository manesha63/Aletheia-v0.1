# PostgreSQL Credential Connection Validation Issue

## Problem Description

n8n shows "can't connect" error for PostgreSQL credentials in the UI, even when the credentials are correctly configured and the database connection is functional.

## Symptoms

1. PostgreSQL credential shows red "Connection failed" status in n8n Credentials page
2. PostgreSQL nodes in workflows show "can't connect with the credentials provided"
3. Despite these UI errors, webhooks and workflows can still execute (though may fail on actual database operations)

## Current State

- PostgreSQL container is running and accessible
- Credentials are correctly stored in n8n database
- Credentials are properly linked to user project
- Password has been simplified to avoid special character issues: `aletheia_secure_pw_2024`
- Connection parameters verified:
  - Host: `db` (Docker network name)
  - Port: `5432`
  - Database: `aletheia`
  - User: `aletheia`
  - SSL: `disable`

## Evidence

1. Credentials exist in database:

```sql
SELECT * FROM credentials_entity WHERE type='postgres';
-- Shows both PMs8mP0nYzWgEu40 and VLnn0kEGUTPNBqW5 credentials
```

2. Credentials are linked to project:

```sql
SELECT * FROM shared_credentials WHERE credentialsId IN ('PMs8mP0nYzWgEu40', 'VLnn0kEGUTPNBqW5');
-- Shows proper project associations
```

3. Direct PostgreSQL connection works:

```bash
docker exec aletheia_development-db-1 psql -U aletheia -d aletheia -c "SELECT 'Connection successful' as status;"
-- Returns: Connection successful
```

4. n8n container logs show authentication failures:

```
password authentication failed for user "aletheia"
FATAL: password authentication failed for user "aletheia"
```

## Root Cause Analysis

The issue appears to be that n8n's credential testing mechanism:

1. May be using incorrect connection parameters (possibly localhost instead of 'db')
2. May not be properly decrypting the stored password
3. May have SSL/TLS configuration mismatches
4. May be testing from a context that doesn't have network access to the database

## Attempted Solutions

1. ✅ Simplified password to remove special characters
2. ✅ Verified database is accessible from within Docker network
3. ✅ Recreated credentials with correct IDs
4. ✅ Ensured credentials are linked to correct project
5. ✅ Set SSL to 'disable' in credential configuration
6. ❌ Connection test still fails in UI

## Proposed Solution

Create a credential validation script that:

1. Tests connection using n8n's actual connection method
2. Verifies network connectivity between containers
3. Validates credential encryption/decryption
4. Provides detailed diagnostic output

## Impact

- **User Experience**: Confusing error messages despite functional setup
- **Development**: Difficult to verify if credentials are actually working
- **Automation**: Can't rely on n8n's built-in credential testing

## Files Involved

- `/n8n/scripts/manage-credentials.sh` - Credential creation script
- `/n8n/scripts/setup-credentials.sh` - Basic credential setup
- `docker-compose.yml` - Container networking configuration
- `.env` - Database credentials

## Priority

High - This creates confusion and prevents proper validation of database connectivity
