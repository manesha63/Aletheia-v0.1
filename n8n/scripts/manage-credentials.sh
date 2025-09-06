#!/bin/sh
# n8n Comprehensive Credential Management Script
# This script handles credential creation, validation, and workflow population

DB_PATH="/data/.n8n/database.sqlite"
LOG_PREFIX="[Credential Manager]"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}${LOG_PREFIX}${NC} $1"
}

log_success() {
    echo -e "${GREEN}${LOG_PREFIX}${NC} ✓ $1"
}

log_warning() {
    echo -e "${YELLOW}${LOG_PREFIX}${NC} ⚠ $1"
}

log_error() {
    echo -e "${RED}${LOG_PREFIX}${NC} ✗ $1"
}

# Wait for database to be ready
wait_for_database() {
    local max_wait=30
    local waited=0
    
    while [ ! -f "$DB_PATH" ]; do
        if [ $waited -ge $max_wait ]; then
            log_error "Database not ready after ${max_wait} seconds"
            return 1
        fi
        log_info "Waiting for n8n database... ($waited/$max_wait)"
        sleep 2
        waited=$((waited + 2))
    done
    
    log_success "Database ready"
    return 0
}

# Get the project ID for the n8n user
get_project_id() {
    PROJECT_ID=$(sqlite3 "$DB_PATH" "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1;" 2>/dev/null)
    
    if [ -z "$PROJECT_ID" ]; then
        PROJECT_ID="personal-auto-setup-user"
        log_warning "Using default project: $PROJECT_ID"
    else
        log_info "Found project: $PROJECT_ID"
    fi
    
    echo "$PROJECT_ID"
}

# Test PostgreSQL connection
test_postgres_connection() {
    local host="$1"
    local port="$2"
    local database="$3"
    local user="$4"
    local password="$5"
    
    # Create a test SQL that n8n would run
    cat > /tmp/test_connection.js << EOF
const { Client } = require('pg');
const client = new Client({
    host: '${host}',
    port: ${port},
    database: '${database}',
    user: '${user}',
    password: '${password}',
    ssl: false
});

client.connect()
    .then(() => {
        console.log('SUCCESS');
        client.end();
        process.exit(0);
    })
    .catch(err => {
        console.error('FAILED:', err.message);
        process.exit(1);
    });
EOF
    
    # Try to test with node (n8n has node and pg library)
    if node /tmp/test_connection.js 2>/dev/null | grep -q "SUCCESS"; then
        rm -f /tmp/test_connection.js
        return 0
    else
        rm -f /tmp/test_connection.js
        return 1
    fi
}

# Create or update a credential with validation
setup_credential() {
    local CRED_ID="$1"
    local CRED_NAME="$2"
    local CRED_TYPE="$3"
    local CRED_JSON="$4"
    local PROJECT_ID="$5"
    
    # Check if credential exists
    EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity WHERE id='$CRED_ID';" 2>/dev/null || echo "0")
    
    if [ "$EXISTS" != "0" ]; then
        # Delete existing credential to avoid encryption issues
        sqlite3 "$DB_PATH" "DELETE FROM shared_credentials WHERE credentialsId='$CRED_ID';" 2>/dev/null
        sqlite3 "$DB_PATH" "DELETE FROM credentials_entity WHERE id='$CRED_ID';" 2>/dev/null
        log_info "Removed existing credential: $CRED_NAME"
    fi
    
    # Create credential JSON file
    echo "[$CRED_JSON]" > /tmp/cred_${CRED_ID}.json
    
    # Import credential using n8n CLI (ensures proper encryption)
    if n8n import:credentials --input=/tmp/cred_${CRED_ID}.json 2>&1 | grep -q "Successfully imported"; then
        # Link to project
        sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                            VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'));" 2>/dev/null
        log_success "Created credential: $CRED_NAME"
        
        # Clean up
        rm -f /tmp/cred_${CRED_ID}.json
        return 0
    else
        log_error "Failed to create credential: $CRED_NAME"
        rm -f /tmp/cred_${CRED_ID}.json
        return 1
    fi
}

# Update workflow to use correct credential IDs
update_workflow_credentials() {
    local WORKFLOW_ID="$1"
    local WORKFLOW_NAME="$2"
    
    log_info "Updating credentials in workflow: $WORKFLOW_NAME"
    
    # Get the workflow nodes
    NODES=$(sqlite3 "$DB_PATH" "SELECT nodes FROM workflow_entity WHERE id='$WORKFLOW_ID';" 2>/dev/null)
    
    if [ -z "$NODES" ]; then
        log_warning "No nodes found for workflow: $WORKFLOW_NAME"
        return 1
    fi
    
    # Update PostgreSQL credential references
    # Replace any postgres credential ID with VLnn0kEGUTPNBqW5 (the one Main Workflow expects)
    UPDATED_NODES=$(echo "$NODES" | sed 's/"id":"[^"]*","name":"Postgres[^"]*"/"id":"VLnn0kEGUTPNBqW5","name":"Postgres account"/g')
    
    # Update Anthropic credential references
    UPDATED_NODES=$(echo "$UPDATED_NODES" | sed 's/"id":"[^"]*","name":"Anthropic[^"]*"/"id":"eT6Unj67DfYj73os","name":"Anthropic account"/g')
    
    # Update the workflow in database
    sqlite3 "$DB_PATH" "UPDATE workflow_entity SET nodes='$UPDATED_NODES' WHERE id='$WORKFLOW_ID';" 2>/dev/null
    
    log_success "Updated workflow credentials: $WORKFLOW_NAME"
    return 0
}

# Main execution
main() {
    log_info "Starting credential management..."
    
    # Wait for database
    if ! wait_for_database; then
        exit 1
    fi
    
    # Get project ID
    PROJECT_ID=$(get_project_id)
    
    # Setup PostgreSQL credentials
    log_info "Setting up PostgreSQL credentials..."
    
    # Get database credentials from environment
    DB_HOST="db"
    DB_PORT="5432"
    DB_DATABASE="${DB_NAME:-aletheia}"
    DB_USER="${DB_USER:-aletheia}"
    DB_PASS="${DB_PASSWORD:-aletheia_secure_pw_2024}"
    
    # Test PostgreSQL connection first
    log_info "Testing PostgreSQL connection..."
    if test_postgres_connection "$DB_HOST" "$DB_PORT" "$DB_DATABASE" "$DB_USER" "$DB_PASS"; then
        log_success "PostgreSQL connection successful"
    else
        log_warning "PostgreSQL connection test failed (may work anyway)"
    fi
    
    # Create both PostgreSQL credentials (for different workflow compatibility)
    POSTGRES_JSON1='{
        "id": "PMs8mP0nYzWgEu40",
        "name": "Postgres Main",
        "type": "postgres",
        "data": {
            "host": "'$DB_HOST'",
            "port": '$DB_PORT',
            "database": "'$DB_DATABASE'",
            "user": "'$DB_USER'",
            "password": "'$DB_PASS'",
            "ssl": "disable"
        }
    }'
    setup_credential "PMs8mP0nYzWgEu40" "Postgres Main" "postgres" "$POSTGRES_JSON1" "$PROJECT_ID"
    
    POSTGRES_JSON2='{
        "id": "VLnn0kEGUTPNBqW5",
        "name": "Postgres account",
        "type": "postgres",
        "data": {
            "host": "'$DB_HOST'",
            "port": '$DB_PORT',
            "database": "'$DB_DATABASE'",
            "user": "'$DB_USER'",
            "password": "'$DB_PASS'",
            "ssl": "disable"
        }
    }'
    setup_credential "VLnn0kEGUTPNBqW5" "Postgres account" "postgres" "$POSTGRES_JSON2" "$PROJECT_ID"
    
    # Setup Anthropic credential if API key is provided
    if [ -n "${ANTHROPIC_API_KEY}" ]; then
        log_info "Setting up Anthropic credential..."
        
        ANTHROPIC_JSON='{
            "id": "eT6Unj67DfYj73os",
            "name": "Anthropic account",
            "type": "anthropicApi",
            "data": {
                "apiKey": "'${ANTHROPIC_API_KEY}'"
            }
        }'
        setup_credential "eT6Unj67DfYj73os" "Anthropic account" "anthropicApi" "$ANTHROPIC_JSON" "$PROJECT_ID"
    else
        log_warning "No Anthropic API key provided (set ANTHROPIC_API_KEY in .env)"
    fi
    
    # Setup OpenAI credential if API key is provided
    if [ -n "${OPENAI_API_KEY}" ]; then
        log_info "Setting up OpenAI credential..."
        
        OPENAI_JSON='{
            "id": "openai-default",
            "name": "OpenAI account",
            "type": "openAiApi",
            "data": {
                "apiKey": "'${OPENAI_API_KEY}'"
            }
        }'
        setup_credential "openai-default" "OpenAI account" "openAiApi" "$OPENAI_JSON" "$PROJECT_ID"
    else
        log_warning "No OpenAI API key provided (set OPENAI_API_KEY in .env)"
    fi
    
    # Update all workflows to use correct credential IDs
    log_info "Updating workflow credentials..."
    
    # Get all workflows
    WORKFLOWS=$(sqlite3 "$DB_PATH" "SELECT id, name FROM workflow_entity;" 2>/dev/null)
    
    if [ -n "$WORKFLOWS" ]; then
        echo "$WORKFLOWS" | while IFS='|' read -r WF_ID WF_NAME; do
            update_workflow_credentials "$WF_ID" "$WF_NAME"
        done
    else
        log_warning "No workflows found to update"
    fi
    
    # Final summary
    log_info "=== Credential Summary ==="
    
    # Count credentials
    CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo "0")
    log_info "Total credentials: $CRED_COUNT"
    
    # List credentials
    sqlite3 "$DB_PATH" "SELECT ce.name, ce.type, CASE WHEN sc.projectId IS NOT NULL THEN 'Linked' ELSE 'Unlinked' END 
                         FROM credentials_entity ce 
                         LEFT JOIN shared_credentials sc ON ce.id = sc.credentialsId
                         ORDER BY ce.type, ce.name;" 2>/dev/null | while IFS='|' read -r NAME TYPE STATUS; do
        if [ "$STATUS" = "Linked" ]; then
            log_success "$TYPE: $NAME [$STATUS]"
        else
            log_warning "$TYPE: $NAME [$STATUS]"
        fi
    done
    
    log_success "Credential management complete!"
}

# Run main function
main "$@"