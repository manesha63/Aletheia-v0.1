# n8n Multiple Import Scripts Causing Workflow Duplication

## Problem Summary
Four different scripts attempt to import workflows during startup, causing duplicate workflows, race conditions, and confusion about which workflows should be loaded. This violates the single responsibility principle and makes the system unpredictable.

## Current Behavior
Multiple scripts import workflows from different sources:
1. `init-workflows.sh` → imports from `/workflows/` (supposed entrypoint, not actually used)
2. `dev-startup.sh` → imports from `/workflows/` (actual entrypoint via /usr/local/bin/dev-startup)
3. `auto-setup.sh` → imports from `/workflow_json/` (called by some scripts)
4. `import-workflows.sh` → another import script (unclear when used)

Result: 9 workflows in database when only 1 ("central") should exist.

## Root Causes

### 1. Confusing Entrypoint Chain
```
Dockerfile.n8n ENTRYPOINT → /entrypoint.sh → /usr/local/bin/dev-startup
                         ↘ /fix-custom-nodes.sh
```
Not:
```
Dockerfile.custom ENTRYPOINT → /data/init-workflows.sh (what we thought)
```

### 2. Different Import Sources
- `/workflows/` - Baked into Docker image (old files)
- `/workflow_json/` - Mounted from host (current files)
- Both get imported, causing duplicates

### 3. No Import Coordination
- No check if workflows already exist
- No marker to prevent re-import
- Each script runs independently

## Evidence
```bash
# Multiple import attempts in logs
docker logs aletheia_development-n8n-1 | grep -i import
# Shows imports from different scripts

# Result: duplicate workflows
docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
  "SELECT name, COUNT(*) FROM workflow_entity GROUP BY name"
# Output:
# Main Workflow|3
# Test Standard Nodes Only|2
# central|1
```

## Current Script Responsibilities

### n8n/entrypoint.sh
```bash
#!/bin/sh
echo "🚀 n8n Development Mode"
if [ -f /fix-custom-nodes.sh ]; then
    /fix-custom-nodes.sh
fi
exec /usr/local/bin/dev-startup  # ← Actual startup script
```

### n8n/scripts/dev-startup.sh (The Real Culprit)
- Creates user account
- Imports from `/workflows/` (old files!)
- Sets up credentials
- Activates workflows

### n8n/scripts/auto-setup.sh
- Also creates user account (duplicate!)
- Imports from `/workflow_json/` (correct source)
- Also sets up credentials (duplicate!)

## Proposed Solution

### Single Clean Startup Script
```bash
#!/bin/sh
# n8n/scripts/single-startup.sh - ONE script to rule them all

set -e

# Configuration
DB_PATH="/data/.n8n/database.sqlite"
IMPORT_MARKER="/data/.n8n/.import-complete"
WORKFLOW_SOURCE="/workflow_json"  # Only mount, never bake

# Wait for database
wait_for_database() {
    while [ ! -f "$DB_PATH" ]; do
        sleep 2
    done
    
    while ! sqlite3 "$DB_PATH" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user'" 2>/dev/null; do
        sleep 2
    done
}

# Setup owner (only if needed)
setup_owner_once() {
    local USER_EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM user" 2>/dev/null || echo "0")
    
    if [ "$USER_EXISTS" -eq "0" ]; then
        # Create owner account
        # ... (existing logic)
    fi
}

# Import workflows (only once, only from workflow_json)
import_workflows_once() {
    if [ -f "$IMPORT_MARKER" ]; then
        echo "Workflows already imported"
        return
    fi
    
    local WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    
    if [ "$WORKFLOW_COUNT" -eq "0" ] && [ -d "$WORKFLOW_SOURCE" ]; then
        for workflow in $WORKFLOW_SOURCE/*.json; do
            if [ -f "$workflow" ]; then
                n8n import:workflow --input="$workflow"
            fi
        done
        touch "$IMPORT_MARKER"
    fi
}

# Setup credentials (only from environment)
setup_credentials_once() {
    # Only if not already setup
    # Import from environment variables, not hardcoded
}

# Main
main() {
    wait_for_database
    setup_owner_once
    import_workflows_once
    setup_credentials_once
    
    # Start n8n
    exec n8n start
}

main "$@"
```

## Implementation Steps

### Step 1: Identify Active Script
```bash
# Find what actually runs
docker exec aletheia_development-n8n-1 ps aux | grep -E "startup|init"
docker exec aletheia_development-n8n-1 cat /proc/1/cmdline
```

### Step 2: Consolidate to Single Script
1. Create `n8n/scripts/single-startup.sh`
2. Update `n8n/entrypoint.sh` to call it
3. Remove/disable other import scripts

### Step 3: Update Dockerfile
```dockerfile
# Copy single startup script
COPY ./n8n/scripts/single-startup.sh /usr/local/bin/startup
RUN chmod +x /usr/local/bin/startup

# Simple entrypoint
ENTRYPOINT ["tini", "--", "/usr/local/bin/startup"]
```

### Step 4: Remove Workflow Baking
```dockerfile
# Remove these lines from Dockerfile.n8n
# RUN mkdir -p /workflows
# COPY ./workflow_json/*.json /workflows/
```

## Testing
1. Clear database: `rm -rf n8n_data/*`
2. Rebuild: `./dev rebuild n8n`
3. Check workflows: Should only have "central"
4. Restart: `./dev restart n8n`
5. Check again: Should still only have "central"

## Impact
- **High Priority**: Causes unpredictable behavior
- **Maintenance**: Multiple scripts to maintain
- **Debugging**: Hard to trace which script does what

## Files to Change/Remove
- **Keep**: `n8n/scripts/single-startup.sh` (new, consolidated)
- **Update**: `n8n/entrypoint.sh` (call single-startup)
- **Remove**: `n8n/init-workflows.sh` (not used)
- **Remove**: `n8n/scripts/dev-startup.sh` (replace with single)
- **Remove**: `n8n/scripts/auto-setup.sh` (duplicate functionality)
- **Remove**: `n8n/scripts/import-workflows.sh` (redundant)
- **Update**: `Dockerfile.n8n` (remove workflow copying, use single script)

## Success Criteria
- Only ONE workflow import during startup
- Only from `/workflow_json/` (mounted volume)
- Idempotent (safe to run multiple times)
- Clear logging of what's happening
- No duplicate workflows after restart