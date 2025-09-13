#!/bin/sh
# Single Unified n8n Startup Script
# This is the ONLY script that should handle n8n initialization

set -e

# Configuration
DB_PATH="/data/.n8n/database.sqlite"
WORKFLOW_SOURCE="/workflow_json"  # Mount from host, never bake into image
# Note: IMPORT_MARKER removed - smart sync doesn't need it
SETUP_EMAIL="${N8N_SETUP_EMAIL:-velvetmoon222999@gmail.com}"
SETUP_PASSWORD="${N8N_SETUP_PASSWORD:-admin123}"

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[n8n-startup]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[n8n-startup]${NC} ✓ $1"
}

log_warning() {
    echo -e "${YELLOW}[n8n-startup]${NC} ⚠ $1"
}

log_error() {
    echo -e "${RED}[n8n-startup]${NC} ✗ $1"
}

# Execute SQLite command with retry logic for database locks
sqlite_exec_with_retry() {
    local query="$1"
    local max_retries=10
    local retry_count=0
    local wait_time=1
    
    while [ $retry_count -lt $max_retries ]; do
        if result=$(sqlite3 "$DB_PATH" "$query" 2>&1); then
            echo "$result"
            return 0
        else
            if echo "$result" | grep -q "database is locked"; then
                retry_count=$((retry_count + 1))
                log_warning "Database locked, retry $retry_count/$max_retries (waiting ${wait_time}s)..."
                sleep $wait_time
                wait_time=$((wait_time * 2))  # Exponential backoff
                if [ $wait_time -gt 10 ]; then
                    wait_time=10  # Cap at 10 seconds
                fi
            else
                # Not a lock error, fail immediately
                echo "$result" >&2
                return 1
            fi
        fi
    done
    
    log_error "Failed to execute query after $max_retries retries"
    return 1
}

# Wait for database migrations to complete
wait_for_migrations() {
    log_info "Waiting for database migrations to complete..."
    local max_wait=120
    local waited=0
    
    # First wait for database file
    while [ ! -f "$DB_PATH" ]; do
        if [ $waited -ge $max_wait ]; then
            log_error "Database file not created after ${max_wait}s"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    
    # Wait for migrations table to exist
    while ! sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='migrations'" 2>/dev/null | grep -q "migrations"; do
        if [ $waited -ge $max_wait ]; then
            log_warning "Migrations table not ready after ${max_wait}s"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    
    # Check if all required tables exist
    local tables_ready=false
    while [ "$tables_ready" = false ]; do
        tables_ready=true
        
        for table in "user" "workflow_entity" "credentials_entity" "project" "project_relation"; do
            if ! sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='$table'" 2>/dev/null | grep -q "$table"; then
                tables_ready=false
                break
            fi
        done
        
        if [ "$tables_ready" = true ]; then
            log_success "All required tables are ready"
            break
        fi
        
        if [ $waited -ge $max_wait ]; then
            log_warning "Some tables not ready after ${max_wait}s, continuing anyway"
            break
        fi
        
        sleep 2
        waited=$((waited + 2))
    done
    
    log_success "Database migrations complete (waited ${waited}s)"
    return 0
}

# Wait for n8n startup to stabilize before restart
wait_for_n8n_stable() {
    local max_wait=60
    local waited=0
    local stable_time=10  # Wait for n8n to be stable for 10 seconds
    
    log_info "Waiting for n8n startup to stabilize..."
    
    # Wait for initial startup
    sleep 15
    
    # Check if process is stable (not consuming high CPU)
    local stable_start=$(date +%s)
    while [ $waited -lt $max_wait ]; do
        if kill -0 $N8N_PID 2>/dev/null; then
            local current_time=$(date +%s)
            local stable_duration=$((current_time - stable_start))
            
            if [ $stable_duration -ge $stable_time ]; then
                log_success "n8n startup stabilized"
                return 0
            fi
        else
            log_error "n8n process died during startup"
            return 1
        fi
        
        sleep 2
        waited=$((waited + 2))
    done
    
    log_warning "n8n stability timeout"
    return 0
}

# Setup owner account (only if needed)
setup_owner_once() {
    local IS_SETUP=$(sqlite_exec_with_retry "SELECT value FROM settings WHERE key='userManagement.isInstanceOwnerSetUp'" 2>/dev/null || echo "")
    
    if [ "$IS_SETUP" = "true" ]; then
        log_info "Owner account already exists"
        return 0
    fi
    
    log_info "Creating owner account..."
    
    local USER_ID="auto-setup-user"
    local PROJECT_ID="personal-$USER_ID"
    # Password hash for 'admin123'
    local PASSWORD_HASH='$2b$10$JtP/WWshmO5wNQ9frbf7Xu1BhRrv8ugRC/RqexJOiGv.Q8zWygHTe'
    
    # Use transaction for atomicity
    sqlite_exec_with_retry "BEGIN TRANSACTION;
INSERT INTO user (id, email, firstName, lastName, password, role, disabled, settings, createdAt, updatedAt) 
VALUES ('$USER_ID', '$SETUP_EMAIL', 'Admin', 'User', '$PASSWORD_HASH', 'global:owner', 0, '{}', datetime('now'), datetime('now'));

INSERT INTO project (id, name, type, createdAt, updatedAt) 
VALUES ('$PROJECT_ID', 'Personal Project', 'personal', datetime('now'), datetime('now'));

INSERT INTO project_relation (projectId, userId, role, createdAt, updatedAt) 
VALUES ('$PROJECT_ID', '$USER_ID', 'project:personalOwner', datetime('now'), datetime('now'));

INSERT OR REPLACE INTO settings (key, value, loadOnStartup) 
VALUES ('userManagement.isInstanceOwnerSetUp', 'true', 1);
COMMIT;"
    
    if [ $? -eq 0 ]; then
        log_success "Owner created: $SETUP_EMAIL / $SETUP_PASSWORD"
    else
        log_error "Failed to create owner account"
        return 1
    fi
}

# Smart sync: Keep database in sync with workflow_json directory
# This replaces the old import-once pattern with continuous sync
sync_workflows() {
    if [ ! -d "$WORKFLOW_SOURCE" ]; then
        log_warning "Workflow source directory not found: $WORKFLOW_SOURCE"
        return 0
    fi
    
    log_info "Syncing workflows with $WORKFLOW_SOURCE..."
    
    # Step 1: Remove workflows that don't have corresponding files
    local removed_count=0
    local existing_workflows=$(sqlite_exec_with_retry "SELECT name FROM workflow_entity" 2>/dev/null || echo "")
    
    if [ -n "$existing_workflows" ]; then
        # Use process substitution to avoid subshell issues with counters
        while IFS= read -r workflow_name; do
            if [ -n "$workflow_name" ]; then
                # Check if corresponding file exists (name-workflow.json pattern)
                expected_file="$WORKFLOW_SOURCE/${workflow_name}-workflow.json"
                if [ ! -f "$expected_file" ]; then
                    log_info "  Removing workflow '$workflow_name' (no corresponding file)"
                    sqlite_exec_with_retry "DELETE FROM workflow_entity WHERE name='$workflow_name'"
                    removed_count=$((removed_count + 1))
                fi
            fi
        done <<EOF
$existing_workflows
EOF
    fi
    
    # Step 2: Import workflows that don't exist in database
    local imported_count=0
    for workflow_file in $WORKFLOW_SOURCE/*.json; do
        if [ -f "$workflow_file" ]; then
            local basename=$(basename "$workflow_file")
            
            # Extract workflow name from JSON
            local workflow_name=$(echo '[]' | jq -r --slurpfile workflow "$workflow_file" '$workflow[0].name // empty' 2>/dev/null || echo "")
            
            if [ -n "$workflow_name" ]; then
                # Check if workflow exists in database
                local existing_count=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM workflow_entity WHERE name='$workflow_name'" 2>/dev/null || echo "0")
                
                if [ "$existing_count" -eq "0" ]; then
                    log_info "  Importing: $basename → '$workflow_name'"
                    
                    if n8n import:workflow --input="$workflow_file" 2>/dev/null; then
                        log_success "  Imported: $workflow_name"
                        imported_count=$((imported_count + 1))
                    else
                        log_warning "  Failed to import: $basename"
                    fi
                else
                    log_info "  Workflow '$workflow_name' already exists, skipping"
                fi
            else
                log_warning "  Could not extract workflow name from: $basename"
            fi
        fi
    done
    
    # Step 3: Activate all workflows (ensure they're active after import)
    if [ "$imported_count" -gt "0" ]; then
        sqlite_exec_with_retry "UPDATE workflow_entity SET active=1 WHERE active=0"
        log_success "Activated $imported_count new workflow(s)"
    fi
    
    # Summary
    local final_count=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    log_success "Workflow sync complete: $final_count workflow(s) active (imported: $imported_count, removed: $removed_count)"
    
    # List current workflows for confirmation
    if [ "$final_count" -gt "0" ]; then
        local workflow_list=$(sqlite_exec_with_retry "SELECT name FROM workflow_entity ORDER BY name" 2>/dev/null || echo "")
        if [ -n "$workflow_list" ]; then
            log_info "Active workflows: $(echo "$workflow_list" | tr '\n' ', ' | sed 's/,$//')"
        fi
    fi
}

# Setup credentials from environment
setup_credentials_once() {
    log_info "Setting up credentials..."
    
    # Get project ID (without log pollution)
    local PROJECT_ID=$(sqlite_exec_with_retry "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1" 2>/dev/null || echo "personal-auto-setup-user")
    
    # PostgreSQL credential
    if [ -n "${DB_PASSWORD}" ]; then
        local POSTGRES_EXISTS=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM credentials_entity WHERE name='Postgres account'" 2>/dev/null || echo "0")
        
        if [ "$POSTGRES_EXISTS" -eq "0" ]; then
            log_info "Creating PostgreSQL credential..."
            
            cat > /tmp/postgres_cred.json << EOF
[{
    "name": "Postgres account",
    "type": "postgres",
    "data": {
        "host": "db",
        "port": 5432,
        "database": "${DB_NAME:-aletheia}",
        "user": "${DB_USER:-aletheia}",
        "password": "${DB_PASSWORD:-aletheia_secure_pw_2024}",
        "ssl": "disable"
    }
}]
EOF
            
            if n8n import:credentials --input=/tmp/postgres_cred.json 2>&1 | grep -q "Successfully imported"; then
                # Get the created credential ID and link it
                local CRED_ID=$(sqlite_exec_with_retry "SELECT id FROM credentials_entity WHERE name='Postgres account' ORDER BY createdAt DESC LIMIT 1" 2>/dev/null)
                
                if [ -n "$CRED_ID" ]; then
                    sqlite_exec_with_retry "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                                        VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'))"
                    log_success "PostgreSQL credential created"
                fi
            fi
            
            rm -f /tmp/postgres_cred.json
        fi
    fi
    
    # Anthropic credential
    if [ -n "${ANTHROPIC_API_KEY}" ]; then
        local ANTHROPIC_EXISTS=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM credentials_entity WHERE name='Anthropic account'" 2>/dev/null || echo "0")
        
        if [ "$ANTHROPIC_EXISTS" -eq "0" ]; then
            log_info "Creating Anthropic credential..."
            
            cat > /tmp/anthropic_cred.json << EOF
[{
    "name": "Anthropic account",
    "type": "anthropicApi",
    "data": {
        "apiKey": "${ANTHROPIC_API_KEY}"
    }
}]
EOF
            
            if n8n import:credentials --input=/tmp/anthropic_cred.json 2>&1 | grep -q "Successfully imported"; then
                # Get the created credential ID and link it
                local CRED_ID=$(sqlite_exec_with_retry "SELECT id FROM credentials_entity WHERE name='Anthropic account' ORDER BY createdAt DESC LIMIT 1" 2>/dev/null)
                
                if [ -n "$CRED_ID" ]; then
                    sqlite_exec_with_retry "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                                        VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'))"
                    log_success "Anthropic credential created"
                fi
            fi
            
            rm -f /tmp/anthropic_cred.json
        fi
    fi
}

# Legacy cleanup function - replaced with smart sync
# This function is kept for compatibility but now just logs
cleanup_duplicates() {
    log_info "Legacy cleanup disabled - using smart sync instead"
    
    # Check for any orphaned workflows (defensive)
    local workflow_count=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    if [ "$workflow_count" -gt "10" ]; then
        log_warning "Found $workflow_count workflows - this seems excessive, consider reviewing"
    fi
}

# Main execution
main() {
    log_info "=== n8n Single Startup Script ==="
    
    # Ensure custom nodes directory exists and restore from global modules
    if [ ! -d "/data/.n8n/custom" ]; then
        log_info "Creating custom nodes directory..."
        mkdir -p /data/.n8n/custom
    fi
    
    # Restore custom nodes from global node_modules to tmpfs location
    log_info "Restoring custom nodes from global modules..."
    restored_count=0
    for node_dir in /usr/local/lib/node_modules/n8n-nodes-*; do
        if [ -d "$node_dir" ]; then
            node_name=$(basename "$node_dir")
            cp -r "$node_dir" "/data/.n8n/custom/"
            log_success "Restored: $node_name"
            restored_count=$((restored_count + 1))
        fi
    done
    
    if [ $restored_count -gt 0 ]; then
        log_success "Restored $restored_count custom nodes"
    else
        log_warning "No custom nodes found to restore"
    fi
    
    # Start n8n in background for database initialization
    log_info "Starting n8n for database initialization..."
    n8n start &
    N8N_PID=$!
    
    # Wait for migrations to complete
    if ! wait_for_migrations; then
        log_error "Failed to wait for migrations"
        kill $N8N_PID 2>/dev/null || true
        exit 1
    fi
    
    # Wait for n8n startup to stabilize (includes custom node discovery)
    if ! wait_for_n8n_stable; then
        log_warning "n8n startup may not be fully stable"
    fi
    
    # Now stop n8n to perform setup without conflicts
    log_info "Stopping n8n for setup phase..."
    kill $N8N_PID 2>/dev/null || true
    wait $N8N_PID 2>/dev/null || true
    
    # Run setup steps with database now available and no locks
    log_info "Running setup steps..."
    setup_owner_once
    cleanup_duplicates  # Legacy function - now just logs
    sync_workflows      # New smart sync replaces import_workflows_once
    setup_credentials_once
    
    # Always run credential manager if API keys are present
    # This ensures credentials are properly linked to workflows
    if [ -n "${ANTHROPIC_API_KEY}" ] || [ -n "${OPENAI_API_KEY}" ]; then
        log_info "Running credential manager to link API credentials..."
        if [ -f "/scripts/manage-credentials.sh" ]; then
            /scripts/manage-credentials.sh
        fi
    fi
    
    # Note: API key setup is handled by auto-login.sh after n8n starts
    # since it requires the n8n API to be running
    
    # Summary
    local WORKFLOW_COUNT=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    local CRED_COUNT=$(sqlite_exec_with_retry "SELECT COUNT(*) FROM credentials_entity" 2>/dev/null || echo "0")
    
    log_info "=== Startup Complete ==="
    log_info "Workflows: $WORKFLOW_COUNT"
    log_info "Credentials: $CRED_COUNT"
    log_info "Login: $SETUP_EMAIL / $SETUP_PASSWORD"
    
    # No need to wait or stop n8n - it's already stopped after migrations
    
    # Start n8n in foreground for production use
    log_info "Starting n8n in production mode..."
    exec n8n start
}

# Run if not sourced
if [ "$1" != "source" ]; then
    main "$@"
fi