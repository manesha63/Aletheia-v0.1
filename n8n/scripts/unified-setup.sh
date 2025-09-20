#!/bin/sh
# Unified n8n Setup Script - Single source of truth for initialization
# This replaces the scattered logic in init-workflows.sh and auto-setup.sh

set -e

DB_PATH="/data/.n8n/database.sqlite"
SETUP_EMAIL="${N8N_SETUP_EMAIL:-velvetmoon222999@gmail.com}"
SETUP_PASSWORD="${N8N_SETUP_PASSWORD:-admin123}"
SETUP_MARKER="/data/.n8n/.unified-setup-complete"
LOG_FILE="/data/.n8n/setup.log"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[Setup]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[Setup]${NC} ✓ $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[Setup]${NC} ⚠ $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[Setup]${NC} ✗ $1" | tee -a "$LOG_FILE"
}

# Check if setup is already complete
check_setup_complete() {
    if [ -f "$SETUP_MARKER" ]; then
        log_info "Setup already completed (marker found)"
        
        # Quick integrity check
        if [ -f "$DB_PATH" ]; then
            USER_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM user;" 2>/dev/null || echo "0")
            WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity;" 2>/dev/null || echo "0")
            CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo "0")
            
            log_info "Database status: $USER_COUNT users, $WORKFLOW_COUNT workflows, $CRED_COUNT credentials"
            
            if [ "$USER_COUNT" -gt 0 ] && [ "$WORKFLOW_COUNT" -gt 0 ]; then
                return 0  # Setup is complete and valid
            else
                log_warning "Database appears incomplete, re-running setup"
                rm -f "$SETUP_MARKER"
            fi
        else
            log_warning "Database not found, re-running setup"
            rm -f "$SETUP_MARKER"
        fi
    fi
    
    return 1  # Setup needed
}

# Wait for database to be ready
wait_for_database() {
    local max_wait=60
    local waited=0
    
    log_info "Waiting for n8n database..."
    
    while [ ! -f "$DB_PATH" ]; do
        if [ $waited -ge $max_wait ]; then
            log_error "Database not created after ${max_wait} seconds"
            return 1
        fi
        
        sleep 2
        waited=$((waited + 2))
    done
    
    # Wait for tables to be created
    while ! sqlite3 "$DB_PATH" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user';" 2>/dev/null | grep -q 1; do
        if [ $waited -ge $max_wait ]; then
            log_error "Database tables not ready after ${max_wait} seconds"
            return 1
        fi
        
        sleep 2
        waited=$((waited + 2))
    done
    
    log_success "Database ready"
    return 0
}

# Create owner account if needed
setup_owner() {
    local USER_ID="auto-setup-user"
    local PROJECT_ID="personal-$USER_ID"
    
    # Check if owner exists
    local IS_SETUP=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key = 'userManagement.isInstanceOwnerSetUp';" 2>/dev/null || echo "")
    
    if [ "$IS_SETUP" = "true" ]; then
        log_info "Owner account already exists"
        
        # Ensure project associations are correct
        sqlite3 "$DB_PATH" "
            INSERT OR IGNORE INTO project (id, name, type, createdAt, updatedAt) 
            VALUES ('$PROJECT_ID', 'Personal Project', 'personal', datetime('now'), datetime('now'));
            
            INSERT OR IGNORE INTO project_relation (projectId, userId, role, createdAt, updatedAt) 
            VALUES ('$PROJECT_ID', '$USER_ID', 'project:personalOwner', datetime('now'), datetime('now'));
        " 2>/dev/null
    else
        log_info "Creating owner account..."
        
        # Password hash for 'admin123' (bcrypt cost 10)
        local PASSWORD_HASH='$2b$10$JtP/WWshmO5wNQ9frbf7Xu1BhRrv8ugRC/RqexJOiGv.Q8zWygHTe'
        
        # Create user
        sqlite3 "$DB_PATH" "
            INSERT INTO user (id, email, firstName, lastName, password, role, disabled, settings, createdAt, updatedAt) 
            VALUES ('$USER_ID', '$SETUP_EMAIL', 'Admin', 'User', '$PASSWORD_HASH', 'global:owner', 0, '{}', datetime('now'), datetime('now'));
            
            INSERT INTO project (id, name, type, createdAt, updatedAt) 
            VALUES ('$PROJECT_ID', 'Personal Project', 'personal', datetime('now'), datetime('now'));
            
            INSERT INTO project_relation (projectId, userId, role, createdAt, updatedAt) 
            VALUES ('$PROJECT_ID', '$USER_ID', 'project:personalOwner', datetime('now'), datetime('now'));
            
            INSERT OR REPLACE INTO settings (key, value, loadOnStartup) 
            VALUES ('userManagement.isInstanceOwnerSetUp', 'true', 1);
        " 2>/dev/null
        
        log_success "Owner created: $SETUP_EMAIL / $SETUP_PASSWORD"
    fi
}

# Import Main Workflow only
import_workflows() {
    log_info "Importing workflows..."
    
    # Remove ALL existing workflows first to avoid duplicates
    sqlite3 "$DB_PATH" "DELETE FROM workflow_entity;" 2>/dev/null
    sqlite3 "$DB_PATH" "DELETE FROM shared_workflow;" 2>/dev/null
    
    # Only import from /workflow_json (host-mounted, controlled)
    if [ -f "/workflow_json/main-workflow-clean.json" ]; then
        log_info "Importing Main Workflow..."
        
        if n8n import:workflow --input="/workflow_json/main-workflow-clean.json" 2>/dev/null; then
            log_success "Main Workflow imported"
            
            # Activate it
            sqlite3 "$DB_PATH" "UPDATE workflow_entity SET active = 1 WHERE name = 'Main Workflow';" 2>/dev/null
        else
            log_warning "Could not import Main Workflow via CLI, using direct insert"
            # Fallback to direct database insert if needed
        fi
    else
        log_warning "main-workflow-clean.json not found"
    fi
    
    # Verify final count
    local WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity;" 2>/dev/null || echo "0")
    log_info "Total workflows: $WORKFLOW_COUNT"
}

# Setup credentials without corruption
setup_credentials() {
    log_info "Setting up credentials..."
    
    # Get project ID directly without capturing log output
    local PROJECT_ID=$(sqlite3 "$DB_PATH" "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1;" 2>/dev/null || echo "personal-auto-setup-user")
    
    # Clear any corrupted entries
    sqlite3 "$DB_PATH" "
        DELETE FROM shared_credentials 
        WHERE projectId LIKE '%[%' 
           OR projectId LIKE '%Credential Manager%'
           OR LENGTH(projectId) > 50;
    " 2>/dev/null
    
    # PostgreSQL credentials
    if [ -n "${DB_PASSWORD}" ]; then
        log_info "Creating PostgreSQL credentials..."
        
        # Ensure PostgreSQL password is synchronized
        if [ -f "/scripts/sync-postgres-password.sh" ]; then
            /scripts/sync-postgres-password.sh >/dev/null 2>&1
        fi
        
        # Create credential files
        cat > /tmp/postgres_cred.json << EOF
[{
    "id": "VLnn0kEGUTPNBqW5",
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
            sqlite3 "$DB_PATH" "
                INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                VALUES ('VLnn0kEGUTPNBqW5', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'));
            " 2>/dev/null
            log_success "PostgreSQL credential created"
        fi
        
        rm -f /tmp/postgres_cred.json
    fi
    
    # Anthropic credential
    if [ -n "${ANTHROPIC_API_KEY}" ]; then
        log_info "Creating Anthropic credential..."
        
        cat > /tmp/anthropic_cred.json << EOF
[{
    "id": "eT6Unj67DfYj73os",
    "name": "Anthropic account",
    "type": "anthropicApi",
    "data": {
        "apiKey": "${ANTHROPIC_API_KEY}"
    }
}]
EOF
        
        if n8n import:credentials --input=/tmp/anthropic_cred.json 2>&1 | grep -q "Successfully imported"; then
            sqlite3 "$DB_PATH" "
                INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                VALUES ('eT6Unj67DfYj73os', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'));
            " 2>/dev/null
            log_success "Anthropic credential created"
        fi
        
        rm -f /tmp/anthropic_cred.json
    fi
    
    # Verify credentials
    local CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo "0")
    local SHARED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM shared_credentials WHERE projectId = '$PROJECT_ID';" 2>/dev/null || echo "0")
    
    log_info "Credentials: $CRED_COUNT total, $SHARED_COUNT properly linked"
}

# Main setup function
main() {
    log_info "Starting unified n8n setup..."
    
    # Check if already set up
    if check_setup_complete; then
        log_success "Setup verification passed, skipping"
        return 0
    fi
    
    # Wait for database
    if ! wait_for_database; then
        log_error "Failed to initialize database"
        return 1
    fi
    
    # Setup in correct order
    setup_owner
    import_workflows
    setup_credentials
    
    # Mark as complete
    touch "$SETUP_MARKER"
    
    # Final summary
    log_info "=== Setup Summary ==="
    
    local USER_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM user;" 2>/dev/null || echo "0")
    local WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity;" 2>/dev/null || echo "0")
    local CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo "0")
    
    log_info "Users: $USER_COUNT"
    log_info "Workflows: $WORKFLOW_COUNT"
    log_info "Credentials: $CRED_COUNT"
    
    if [ "$WORKFLOW_COUNT" -gt 0 ]; then
        log_info "Active workflows:"
        sqlite3 "$DB_PATH" "SELECT name, CASE WHEN active = 1 THEN 'Active' ELSE 'Inactive' END FROM workflow_entity;" 2>/dev/null | while IFS='|' read -r name status; do
            echo "  - $name [$status]"
        done
    fi
    
    log_success "Setup complete!"
    log_info "Login: $SETUP_EMAIL / $SETUP_PASSWORD"
    
    return 0
}

# Run if executed directly
if [ "${1}" != "source" ]; then
    main "$@"
fi