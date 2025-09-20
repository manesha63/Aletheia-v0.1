#!/bin/bash
# PostgreSQL Password Synchronization Script (Host-side)
# Ensures the database password matches the environment configuration

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
    echo -e "${BLUE}[Password Sync]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[Password Sync]${NC} ✓ $1"
}

log_warning() {
    echo -e "${YELLOW}[Password Sync]${NC} ⚠ $1"
}

log_error() {
    echo -e "${RED}[Password Sync]${NC} ✗ $1"
}

# Get credentials
DB_USER="${DB_USER:-aletheia}"
DB_PASSWORD="${DB_PASSWORD:-aletheia_secure_pw_2024}"
DB_NAME="${DB_NAME:-aletheia}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-aletheia_development}"

log_info "Synchronizing PostgreSQL password for user: $DB_USER"

# Check if database container is running
if ! docker ps --format "table {{.Names}}" | grep -q "${COMPOSE_PROJECT}-db-1"; then
    log_error "Database container is not running"
    log_info "Start services with: ./dev up"
    exit 1
fi

# Reset the password in PostgreSQL
log_info "Updating password in database..."
if docker exec "${COMPOSE_PROJECT}-db-1" psql -U "$DB_USER" -d "$DB_NAME" -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null 2>&1; then
    log_success "Password updated successfully"
else
    log_warning "Could not update password (may already be correct)"
fi

# Test the connection from database container
log_info "Testing connection from database container..."
if docker exec "${COMPOSE_PROJECT}-db-1" sh -c "PGPASSWORD='$DB_PASSWORD' psql -U $DB_USER -d $DB_NAME -c 'SELECT 1;'" >/dev/null 2>&1; then
    log_success "Database connection successful"
else
    log_error "Database connection failed"
    exit 1
fi

# Test connection from n8n container if running
if docker ps --format "table {{.Names}}" | grep -q "${COMPOSE_PROJECT}-n8n-1"; then
    log_info "Testing connection from n8n container..."
    
    TEST_SCRIPT='
const { Client } = require("pg");
const client = new Client({
    host: "db",
    port: 5432,
    database: "'$DB_NAME'",
    user: "'$DB_USER'",
    password: "'$DB_PASSWORD'",
    ssl: false
});
client.connect()
    .then(() => { console.log("SUCCESS"); client.end(); process.exit(0); })
    .catch(err => { console.log("ERROR:", err.message); process.exit(1); });
'
    
    if docker exec "${COMPOSE_PROJECT}-n8n-1" sh -c "cd /usr/local/lib/node_modules/n8n && node -e '$TEST_SCRIPT'" 2>&1 | grep -q "SUCCESS"; then
        log_success "n8n can connect to PostgreSQL"
        
        # Recreate credentials if they exist
        log_info "Updating n8n credentials..."
        if docker exec "${COMPOSE_PROJECT}-n8n-1" test -f /scripts/manage-credentials.sh; then
            docker exec "${COMPOSE_PROJECT}-n8n-1" /scripts/manage-credentials.sh >/dev/null 2>&1
            log_success "Credentials updated"
        fi
    else
        log_error "n8n cannot connect to PostgreSQL"
        log_info "Try restarting n8n: docker-compose restart n8n"
    fi
else
    log_info "n8n container not running, skipping n8n tests"
fi

log_success "Password synchronization complete!"
log_info "If credentials still show as disconnected in n8n UI:"
log_info "  1. Go to Credentials page"
log_info "  2. Open each PostgreSQL credential"
log_info "  3. Click 'Test connection'"
log_info "  4. Save if connection is successful"