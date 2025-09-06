# n8n Workflow Persistence and State Synchronization Issue

## Problem Summary
Workflows edited and saved in n8n UI are not persisted to the repository, causing old workflows to be re-imported on every container rebuild. This creates a state synchronization problem between the repository (source of truth for deployment) and the n8n database (working state).

## Current Behavior
1. User edits/saves workflow "central" in n8n UI → stored in SQLite database
2. Container rebuild occurs → old workflows from `/workflows/` directory are imported
3. User's changes are lost, replaced with outdated workflows
4. Multiple duplicate workflows accumulate (e.g., 3x "Main Workflow", 2x "Test Standard Nodes Only")

## Root Causes

### 1. Workflows Baked into Docker Image
- `Dockerfile.n8n` line 80: `COPY ./workflow_json/*.json /workflows/`
- Old workflow files are permanently embedded in the image
- Every container start imports these outdated files

### 2. Multiple Import Scripts
Four different scripts attempt to import workflows:
- `n8n/init-workflows.sh` - imports from `/workflows/` 
- `n8n/scripts/dev-startup.sh` - imports from `/workflows/`
- `n8n/scripts/auto-setup.sh` - imports from `/workflow_json/`
- Manual imports via UI

### 3. No Export Mechanism
- Workflows saved in n8n UI remain in SQLite database
- No automated way to export back to repository
- Changes are lost when database volume is recreated

## Evidence
```bash
# Current state shows duplicate workflows
docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite "SELECT name, COUNT(*) FROM workflow_entity GROUP BY name;"
# Output:
# Main Workflow|3
# Test Standard Nodes Only|2
# Hierarchical Summarization Template|2
# central|1  # User's actual workflow
```

## Proposed Solution

### Phase 1: Clean Separation
1. **Remove workflows from Docker image**
   ```dockerfile
   # Dockerfile.n8n - Remove these lines:
   # RUN mkdir -p /workflows
   # COPY ./workflow_json/*.json /workflows/
   ```

2. **Single import mechanism**
   - Create one `n8n/scripts/clean-startup.sh`
   - Import ONLY from `/workflow_json/` (mounted volume)
   - Import ONLY if database is empty (first run)
   - Use marker file to prevent re-imports

3. **Dynamic workflow export**
   ```bash
   # Add to dev CLI
   ./dev n8n export-workflows  # Exports all workflows to workflow_json/
   ./dev n8n export-workflow central  # Export specific workflow
   ```

### Phase 2: Remove Hardcoded IDs
- Webhook IDs should not be hardcoded in workflow files
- Use workflow names for identification
- Credentials should reference by name, not ID

### Phase 3: Clean Repository State
- Keep only `workflow_json/central-workflow.json`
- Remove all other workflow files
- Update import to only load "central" workflow

## Implementation Steps

### Step 1: Create Clean Startup Script
```bash
#!/bin/sh
# n8n/scripts/clean-startup.sh

MARKER="/data/.n8n/.workflows-imported"
DB_PATH="/data/.n8n/database.sqlite"

# Only import if marker doesn't exist
if [ ! -f "$MARKER" ]; then
    # Only import if database is ready and empty
    if [ -f "$DB_PATH" ]; then
        WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
        
        if [ "$WORKFLOW_COUNT" -eq "0" ]; then
            # Import only from workflow_json
            for workflow in /workflow_json/*.json; do
                n8n import:workflow --input="$workflow"
            done
            touch "$MARKER"
        fi
    fi
fi

# Continue with normal startup
exec n8n start
```

### Step 2: Update Dockerfile
```dockerfile
# Remove workflow copying
# Mount at runtime instead via docker-compose volumes
```

### Step 3: Add Export Command to dev CLI
```bash
# In dev-n8n.sh
export-workflows)
    for wf_id in $(docker exec $CONTAINER sqlite3 /data/.n8n/database.sqlite "SELECT id FROM workflow_entity"); do
        docker exec $CONTAINER n8n export:workflow --id=$wf_id --output=/tmp/$wf_id.json
        docker cp $CONTAINER:/tmp/$wf_id.json workflow_json/
    done
    ;;
```

## Testing
1. Save workflow in n8n UI
2. Export with `./dev n8n export-workflows`
3. Rebuild container: `./dev rebuild n8n`
4. Verify workflow persists: `./dev n8n test webhook`

## Impact
- **High Priority**: Blocks reliable deployment and development
- **User Experience**: Lost work when containers rebuild
- **Development**: Cannot share workflow changes via git

## Files Affected
- `Dockerfile.n8n` - Remove workflow copying
- `n8n/scripts/dev-startup.sh` - Change import source
- `n8n/scripts/auto-setup.sh` - Disable duplicate import
- `n8n/init-workflows.sh` - Replace with clean version
- `dev-modules/dev-n8n.sh` - Add export commands
- `workflow_json/` - Clean up old files, keep only central

## Related Issues
- Credential corruption (manage-credentials.sh logging issue)
- Hardcoded webhook IDs breaking on reimport
- Multiple startup scripts causing race conditions