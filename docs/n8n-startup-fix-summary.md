# n8n Startup Issues - Root Cause Analysis and Permanent Solution

## Issues Identified

### 1. Credential Window Hanging
**Root Cause**: In `manage-credentials.sh`, the `get_project_id()` function logged to stdout instead of stderr, corrupting the PROJECT_ID variable with ANSI color codes and log messages.

**Evidence**:
```bash
# Bad: Logs pollute the return value
PROJECT_ID=$(get_project_id)  # Returns: "[0;34m[Credential Manager][0m Found project: personal-auto-setup-user"
```

**Fix**: Redirect logs to stderr
```bash
log_info "Found project: $PROJECT_ID" >&2  # Logs go to stderr, not stdout
```

### 2. Duplicate Workflows
**Root Cause**: Multiple scripts importing workflows from different sources:
- `init-workflows.sh` imports from `/workflows/` (built into Docker image)
- `auto-setup.sh` imports from `/workflow_json/` (mounted from host)
- Both run on container startup, causing duplicates

**Evidence**:
- 13 workflows in database (3x Main Workflow, 3x each other workflow)
- `/workflows/` contains old workflow files
- `/workflow_json/` contains only `main-workflow-clean.json`

### 3. Test Command Bug
**Root Cause**: Extra `}` in test payload default value on line 1554 of `dev-n8n.sh`

**Fix**: Changed from `}}` to `}` in the default JSON

## Permanent Solution

### 1. Unified Setup Script (`unified-setup.sh`)
- Single source of truth for all initialization
- Proper error handling and logging
- Idempotent (safe to run multiple times)
- Clear setup marker to prevent re-runs
- Logs to stderr to avoid variable corruption

### 2. Clean Init Script (`init-workflows-clean.sh`)
- Delegates all setup to unified script
- No duplicate import logic
- Clear execution flow

### 3. Key Improvements
- **No workflow duplication**: Only imports from `/workflow_json/`
- **No credential corruption**: All logs go to stderr or log files
- **Idempotent setup**: Uses marker file and database checks
- **Clean database**: Removes corrupted entries before creating new ones
- **Single workflow source**: Only Main Workflow from controlled location

## Implementation Steps

### For Fresh Setup
1. Replace `init-workflows.sh` with `init-workflows-clean.sh` in Dockerfile
2. Ensure `unified-setup.sh` is in `/scripts/` volume
3. Start container normally with `./dev up`

### For Existing Setup
1. Run database cleanup: `./scripts/fix-n8n-database.sh`
2. Restart n8n: `docker-compose restart n8n`
3. Verify with: `./dev n8n test webhook`

## Verification

### Check Database Integrity
```bash
docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite "
  SELECT 'Users:', COUNT(*) FROM user;
  SELECT 'Workflows:', COUNT(*) FROM workflow_entity;
  SELECT 'Credentials:', COUNT(*) FROM credentials_entity;
  SELECT 'Clean associations:', COUNT(*) FROM shared_credentials WHERE LENGTH(projectId) < 50;
"
```

### Expected Results
- 1 user (auto-setup-user)
- 1 workflow (Main Workflow)
- 2-3 credentials (PostgreSQL, Anthropic if configured)
- All associations clean (no log messages in projectId)

## Files Changed

### Fixed
- `dev-modules/dev-n8n.sh` - Fixed test command JSON bug
- `n8n/scripts/manage-credentials.sh` - Fixed stdout pollution
- `n8n/init-workflows.sh` - Disabled /workflows import

### Created
- `n8n/scripts/unified-setup.sh` - Clean, unified setup logic
- `n8n/init-workflows-clean.sh` - Simplified init script
- `scripts/fix-n8n-database.sh` - Database cleanup tool
- `scripts/sync-postgres-password.sh` - Password synchronization

## Testing
```bash
# Test webhook functionality
./dev n8n test webhook

# Test with custom data
./dev n8n test webhook '{"message": "test"}'

# Check credentials load in UI
# Visit: http://localhost:8100/credentials
```

## Future Improvements
1. Update Dockerfile to use `init-workflows-clean.sh`
2. Remove old scripts after migration
3. Add health checks for credential validity
4. Implement automated testing on startup