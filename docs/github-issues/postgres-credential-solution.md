# PostgreSQL Credential Connection Solution

## Problem Resolved

The PostgreSQL credentials in n8n were showing "can't connect" despite correct configuration.

## Root Cause

The PostgreSQL database container had a different password stored than what was configured in the environment variables. This mismatch occurred because:

1. The database was initially created with a complex password containing special characters
2. The password was later changed in `.env` but the database retained the old password
3. n8n was trying to connect with the new password from environment variables

## Solution Implemented

### 1. Password Synchronization Script

Created `/n8n/scripts/fix-postgres-password.sh` that:

- Resets the PostgreSQL user password to match environment variables
- Verifies connection from n8n container context
- Runs automatically before credential setup

### 2. Updated Auto-Setup Flow

Modified `/n8n/scripts/auto-setup.sh` to:

- Run password synchronization before creating credentials
- Ensure database password always matches environment configuration

### 3. Improved Credential Management

Enhanced `/n8n/scripts/manage-credentials.sh` with:

- Better connection testing using n8n's pg module
- Detailed logging of credential creation
- Automatic workflow credential updates

## Key Files Modified

1. `/n8n/scripts/fix-postgres-password.sh` - New password sync script
2. `/n8n/scripts/auto-setup.sh` - Added password sync step
3. `/n8n/scripts/manage-credentials.sh` - Improved connection testing
4. `/n8n/scripts/validate-postgres-connection.sh` - Diagnostic tool

## Verification Steps

1. Reset database password:

   ```bash
   docker exec aletheia_development-db-1 psql -U aletheia -d aletheia -c "ALTER USER aletheia WITH PASSWORD 'aletheia_secure_pw_2024';"
   ```

2. Test connection from n8n:

   ```bash
   docker exec aletheia_development-n8n-1 /scripts/validate-postgres-connection.sh
   ```

3. Recreate credentials:
   ```bash
   docker exec aletheia_development-n8n-1 /scripts/manage-credentials.sh
   ```

## Prevention

The password synchronization now runs automatically on startup, ensuring:

- Database password always matches environment configuration
- Credentials are created with the correct password
- Connection is verified before credential creation

## Testing

After implementation:

- ✅ PostgreSQL connections work from n8n container
- ✅ Credentials are created successfully
- ✅ Workflows can execute database queries
- ✅ n8n UI should show credentials as connected

## Remaining Considerations

1. n8n's credential test in UI may still fail if encryption key changes
2. Manual credential recreation in UI may be needed after major changes
3. Consider using Docker secrets for production deployments
