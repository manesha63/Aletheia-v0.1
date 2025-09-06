#!/bin/sh
# Single Unified n8n Startup Script
# This is the ONLY script that should handle n8n initialization

set -e

# Configuration
DB_PATH="/data/.n8n/database.sqlite"
IMPORT_MARKER="/data/.n8n/.workflows-imported-v2"
WORKFLOW_SOURCE="/workflow_json"  # Mount from host, never bake into image
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

# Wait for database to be ready
wait_for_database() {
    log_info "Waiting for database..."
    local max_wait=60
    local waited=0
    
    while [ ! -f "$DB_PATH" ]; do
        if [ $waited -ge $max_wait ]; then
            log_warning "Database not ready after ${max_wait}s"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    
    # Wait for tables
    while ! sqlite3 "$DB_PATH" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user'" 2>/dev/null | grep -q 1; do
        if [ $waited -ge $max_wait ]; then
            log_warning "Database tables not ready after ${max_wait}s"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    
    log_success "Database ready"
    return 0
}

# Setup owner account (only if needed)
setup_owner_once() {
    local IS_SETUP=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='userManagement.isInstanceOwnerSetUp'" 2>/dev/null || echo "")
    
    if [ "$IS_SETUP" = "true" ]; then
        log_info "Owner account already exists"
        return 0
    fi
    
    log_info "Creating owner account..."
    
    local USER_ID="auto-setup-user"
    local PROJECT_ID="personal-$USER_ID"
    # Password hash for 'admin123'
    local PASSWORD_HASH='$2b$10$JtP/WWshmO5wNQ9frbf7Xu1BhRrv8ugRC/RqexJOiGv.Q8zWygHTe'
    
    sqlite3 "$DB_PATH" << EOF
INSERT INTO user (id, email, firstName, lastName, password, role, disabled, settings, createdAt, updatedAt) 
VALUES ('$USER_ID', '$SETUP_EMAIL', 'Admin', 'User', '$PASSWORD_HASH', 'global:owner', 0, '{}', datetime('now'), datetime('now'));

INSERT INTO project (id, name, type, createdAt, updatedAt) 
VALUES ('$PROJECT_ID', 'Personal Project', 'personal', datetime('now'), datetime('now'));

INSERT INTO project_relation (projectId, userId, role, createdAt, updatedAt) 
VALUES ('$PROJECT_ID', '$USER_ID', 'project:personalOwner', datetime('now'), datetime('now'));

INSERT OR REPLACE INTO settings (key, value, loadOnStartup) 
VALUES ('userManagement.isInstanceOwnerSetUp', 'true', 1);
EOF
    
    log_success "Owner created: $SETUP_EMAIL / $SETUP_PASSWORD"
}

# Import workflows ONLY from workflow_json, ONLY once
import_workflows_once() {
    # Check marker
    if [ -f "$IMPORT_MARKER" ]; then
        log_info "Workflows already imported (marker found)"
        return 0
    fi
    
    # Check if workflows exist
    local WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    
    if [ "$WORKFLOW_COUNT" -gt "0" ]; then
        log_info "Found $WORKFLOW_COUNT existing workflow(s), skipping import"
        touch "$IMPORT_MARKER"
        return 0
    fi
    
    # Import from workflow_json ONLY
    if [ ! -d "$WORKFLOW_SOURCE" ]; then
        log_warning "Workflow source directory not found: $WORKFLOW_SOURCE"
        return 0
    fi
    
    log_info "Importing workflows from $WORKFLOW_SOURCE..."
    
    for workflow_file in $WORKFLOW_SOURCE/*.json; do
        if [ -f "$workflow_file" ]; then
            local basename=$(basename "$workflow_file")
            log_info "  Importing: $basename"
            
            if n8n import:workflow --input="$workflow_file" 2>/dev/null; then
                log_success "  Imported: $basename"
            else
                log_warning "  Failed to import: $basename"
            fi
        fi
    done
    
    # Mark as complete
    touch "$IMPORT_MARKER"
    
    # Activate workflows
    sqlite3 "$DB_PATH" "UPDATE workflow_entity SET active=1 WHERE active=0" 2>/dev/null
    log_success "Workflows activated"
}

# Setup credentials from environment
setup_credentials_once() {
    log_info "Setting up credentials..."
    
    # Get project ID (without log pollution)
    local PROJECT_ID=$(sqlite3 "$DB_PATH" "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1" 2>/dev/null || echo "personal-auto-setup-user")
    
    # PostgreSQL credential
    if [ -n "${DB_PASSWORD}" ]; then
        local POSTGRES_EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity WHERE name='Postgres account'" 2>/dev/null || echo "0")
        
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
                local CRED_ID=$(sqlite3 "$DB_PATH" "SELECT id FROM credentials_entity WHERE name='Postgres account' ORDER BY createdAt DESC LIMIT 1" 2>/dev/null)
                
                if [ -n "$CRED_ID" ]; then
                    sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                                        VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'))" 2>/dev/null
                    log_success "PostgreSQL credential created"
                fi
            fi
            
            rm -f /tmp/postgres_cred.json
        fi
    fi
    
    # Anthropic credential
    if [ -n "${ANTHROPIC_API_KEY}" ]; then
        local ANTHROPIC_EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity WHERE name='Anthropic account'" 2>/dev/null || echo "0")
        
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
                local CRED_ID=$(sqlite3 "$DB_PATH" "SELECT id FROM credentials_entity WHERE name='Anthropic account' ORDER BY createdAt DESC LIMIT 1" 2>/dev/null)
                
                if [ -n "$CRED_ID" ]; then
                    sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                                        VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'))" 2>/dev/null
                    log_success "Anthropic credential created"
                fi
            fi
            
            rm -f /tmp/anthropic_cred.json
        fi
    fi
}

# Clean up any duplicate or old workflows
cleanup_duplicates() {
    log_info "Cleaning up duplicate workflows..."
    
    # Remove all workflows except 'central'
    sqlite3 "$DB_PATH" "DELETE FROM workflow_entity WHERE name != 'central'" 2>/dev/null
    
    # If no 'central' workflow exists, we'll import it
    local CENTRAL_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity WHERE name='central'" 2>/dev/null || echo "0")
    
    if [ "$CENTRAL_COUNT" -eq "0" ]; then
        log_warning "No 'central' workflow found, will import from workflow_json"
        rm -f "$IMPORT_MARKER"  # Force reimport
    else
        log_success "Found 'central' workflow"
    fi
}

# Main execution
main() {
    log_info "=== n8n Single Startup Script ==="
    
    # Start n8n in background for initialization
    log_info "Starting n8n in background..."
    n8n start &
    N8N_PID=$!
    
    # Wait for database
    if ! wait_for_database; then
        kill $N8N_PID 2>/dev/null || true
        exit 1
    fi
    
    # Run setup steps
    setup_owner_once
    cleanup_duplicates
    import_workflows_once
    setup_credentials_once
    
    # Summary
    local WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    local CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity" 2>/dev/null || echo "0")
    
    log_info "=== Startup Complete ==="
    log_info "Workflows: $WORKFLOW_COUNT"
    log_info "Credentials: $CRED_COUNT"
    log_info "Login: $SETUP_EMAIL / $SETUP_PASSWORD"
    
    # Stop background n8n
    log_info "Stopping background n8n..."
    kill $N8N_PID 2>/dev/null || true
    wait $N8N_PID 2>/dev/null || true
    
    # Copy database to persistent location
    if [ -f "/home/node/.n8n/database.sqlite" ]; then
        cp /home/node/.n8n/database.sqlite /data/database.sqlite 2>/dev/null || true
    fi
    
    # Start n8n in foreground
    log_info "Starting n8n in foreground..."
    exec n8n start
}

# Run if not sourced
if [ "$1" != "source" ]; then
    main "$@"
fi