#!/bin/bash
# Fix corrupted n8n database - remove duplicates and fix credential associations

set -e

# Load environment variables
if [ -f .env ]; then
    source .env
fi

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[Database Fix]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[Database Fix]${NC} ✓ $1"
}

log_warning() {
    echo -e "${YELLOW}[Database Fix]${NC} ⚠ $1"
}

log_error() {
    echo -e "${RED}[Database Fix]${NC} ✗ $1"
}

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-aletheia_development}"

# Check if n8n container is running
if ! docker ps --format "table {{.Names}}" | grep -q "${COMPOSE_PROJECT}-n8n-1"; then
    log_error "n8n container is not running"
    log_info "Start services with: ./dev up"
    exit 1
fi

log_info "Starting database cleanup..."

# Step 1: Clean up corrupted shared_credentials table
log_info "Fixing corrupted credential associations..."
docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite << 'EOF'
-- Remove corrupted entries (those with log messages in projectId)
DELETE FROM shared_credentials 
WHERE projectId LIKE '%[%' 
   OR projectId LIKE '%Credential Manager%'
   OR LENGTH(projectId) > 50;

-- Remove duplicate entries
DELETE FROM shared_credentials
WHERE rowid NOT IN (
    SELECT MIN(rowid)
    FROM shared_credentials
    GROUP BY credentialsId, projectId
);

-- Ensure all credentials are linked to the correct project
INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
SELECT 
    ce.id,
    'personal-auto-setup-user',
    'credential:owner',
    datetime('now'),
    datetime('now')
FROM credentials_entity ce
WHERE ce.id NOT IN (
    SELECT credentialsId 
    FROM shared_credentials 
    WHERE projectId = 'personal-auto-setup-user'
);
EOF

if [ $? -eq 0 ]; then
    log_success "Fixed credential associations"
else
    log_error "Failed to fix credential associations"
fi

# Step 2: Remove duplicate workflows
log_info "Removing duplicate workflows..."

# Get workflow counts before cleanup
BEFORE_COUNT=$(docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM workflow_entity;" 2>/dev/null || echo "0")
log_info "Workflows before cleanup: $BEFORE_COUNT"

# Remove duplicates, keeping only the newest version of each workflow
docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite << 'EOF'
-- First, remove workflows that aren't "Main Workflow"
DELETE FROM workflow_entity 
WHERE name != 'Main Workflow';

-- Then remove duplicates of Main Workflow, keeping the newest
DELETE FROM workflow_entity
WHERE name = 'Main Workflow'
AND id NOT IN (
    SELECT id FROM workflow_entity 
    WHERE name = 'Main Workflow'
    ORDER BY updatedAt DESC
    LIMIT 1
);

-- Clean up orphaned workflow associations
DELETE FROM shared_workflow
WHERE workflowId NOT IN (
    SELECT id FROM workflow_entity
);
EOF

# Step 3: Import the clean Main Workflow if no workflows exist
WORKFLOW_COUNT=$(docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM workflow_entity;" 2>/dev/null || echo "0")

if [ "$WORKFLOW_COUNT" -eq "0" ]; then
    log_warning "No workflows found, importing Main Workflow..."
    
    if [ -f "workflow_json/main-workflow-clean.json" ]; then
        docker exec "${COMPOSE_PROJECT}-n8n-1" sh -c "n8n import:workflow --input=/workflow_json/main-workflow-clean.json" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            log_success "Imported Main Workflow"
        else
            log_warning "Could not import Main Workflow"
        fi
    else
        log_warning "main-workflow-clean.json not found"
    fi
else
    log_success "Found $WORKFLOW_COUNT workflow(s) after cleanup"
fi

# Step 4: Verify the fix
log_info "Verifying database integrity..."

# Check credentials
CRED_COUNT=$(docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo "0")
SHARED_COUNT=$(docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM shared_credentials WHERE projectId = 'personal-auto-setup-user';" 2>/dev/null || echo "0")

log_info "Credentials: $CRED_COUNT"
log_info "Properly linked credentials: $SHARED_COUNT"

# Check for corrupted entries
CORRUPTED=$(docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM shared_credentials WHERE projectId LIKE '%[%' OR LENGTH(projectId) > 50;" 2>/dev/null || echo "0")

if [ "$CORRUPTED" -eq "0" ]; then
    log_success "No corrupted credential entries found"
else
    log_error "Still have $CORRUPTED corrupted entries"
fi

# List final workflows
log_info "Final workflows:"
docker exec "${COMPOSE_PROJECT}-n8n-1" sqlite3 /data/.n8n/database.sqlite "SELECT id, name FROM workflow_entity;" 2>/dev/null | while IFS='|' read -r id name; do
    echo "  - $name (ID: $id)"
done

log_success "Database cleanup complete!"
log_info ""
log_info "Next steps:"
log_info "1. Restart n8n: docker-compose restart n8n"
log_info "2. Login to n8n web interface"
log_info "3. Check that credentials load properly"
log_info "4. Verify only Main Workflow exists"