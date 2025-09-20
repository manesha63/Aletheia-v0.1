#!/bin/sh
# PostgreSQL Connection Validation Script for n8n
# This script tests PostgreSQL connectivity from within the n8n container context

LOG_PREFIX="[PostgreSQL Validator]"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# Test network connectivity
test_network() {
    log_info "Testing network connectivity to database container..."
    
    # Check if we can resolve the hostname
    if ping -c 1 db >/dev/null 2>&1; then
        log_success "Database host 'db' is reachable"
    else
        log_error "Cannot reach database host 'db'"
        
        # Try to get the actual IP
        DB_IP=$(getent hosts db 2>/dev/null | awk '{ print $1 }')
        if [ -n "$DB_IP" ]; then
            log_info "Database host resolves to IP: $DB_IP"
            
            if ping -c 1 "$DB_IP" >/dev/null 2>&1; then
                log_success "Can ping database IP directly"
            else
                log_error "Cannot ping database IP"
            fi
        else
            log_error "Cannot resolve database hostname"
        fi
    fi
    
    # Test port connectivity
    log_info "Testing port 5432 connectivity..."
    if nc -zv db 5432 2>&1 | grep -q succeeded; then
        log_success "Port 5432 is open on database host"
    else
        log_error "Cannot connect to port 5432"
    fi
}

# Test PostgreSQL connection using psql
test_psql_connection() {
    local host="${1:-db}"
    local port="${2:-5432}"
    local database="${3:-aletheia}"
    local user="${4:-aletheia}"
    local password="${5:-aletheia_secure_pw_2024}"
    
    log_info "Testing PostgreSQL connection with psql..."
    log_info "  Host: $host"
    log_info "  Port: $port"
    log_info "  Database: $database"
    log_info "  User: $user"
    
    # Test with psql if available
    if command -v psql >/dev/null 2>&1; then
        export PGPASSWORD="$password"
        
        if psql -h "$host" -p "$port" -U "$user" -d "$database" -c "SELECT version();" >/dev/null 2>&1; then
            log_success "psql connection successful"
            
            # Get some diagnostic info
            VERSION=$(psql -h "$host" -p "$port" -U "$user" -d "$database" -t -c "SELECT version();" 2>/dev/null | head -1)
            log_info "PostgreSQL version: ${VERSION:0:50}..."
            
            return 0
        else
            log_error "psql connection failed"
            return 1
        fi
    else
        log_warning "psql command not available in container"
        return 2
    fi
}

# Test connection using Node.js (how n8n connects)
test_node_connection() {
    local host="${1:-db}"
    local port="${2:-5432}"
    local database="${3:-aletheia}"
    local user="${4:-aletheia}"
    local password="${5:-aletheia_secure_pw_2024}"
    
    log_info "Testing PostgreSQL connection with Node.js (n8n method)..."
    
    # Create test script
    cat > /tmp/test_pg_connection.js << EOF
const { Client } = require('pg');

const config = {
    host: '${host}',
    port: ${port},
    database: '${database}',
    user: '${user}',
    password: '${password}',
    ssl: false,
    connectionTimeoutMillis: 5000
};

console.log('Testing connection with config:', {
    ...config,
    password: '***' // Hide password in logs
});

const client = new Client(config);

client.connect()
    .then(() => {
        console.log('SUCCESS: Connected to PostgreSQL');
        return client.query('SELECT current_database(), current_user, version()');
    })
    .then(result => {
        console.log('Database:', result.rows[0].current_database);
        console.log('User:', result.rows[0].current_user);
        console.log('Version:', result.rows[0].version.split(' ')[0] + ' ' + result.rows[0].version.split(' ')[1]);
        client.end();
        process.exit(0);
    })
    .catch(err => {
        console.error('FAILED:', err.message);
        if (err.code) console.error('Error code:', err.code);
        if (err.detail) console.error('Detail:', err.detail);
        process.exit(1);
    });
EOF

    # Try to run with node
    if node /tmp/test_pg_connection.js 2>&1; then
        log_success "Node.js pg connection successful"
        rm -f /tmp/test_pg_connection.js
        return 0
    else
        log_error "Node.js pg connection failed"
        
        # Try alternative SSL settings
        log_info "Retrying with SSL reject unauthorized disabled..."
        sed -i "s/ssl: false/ssl: { rejectUnauthorized: false }/" /tmp/test_pg_connection.js
        
        if node /tmp/test_pg_connection.js 2>&1; then
            log_warning "Connection works with SSL rejectUnauthorized: false"
            rm -f /tmp/test_pg_connection.js
            return 0
        else
            log_error "Connection still fails with modified SSL settings"
            rm -f /tmp/test_pg_connection.js
            return 1
        fi
    fi
}

# Check n8n credential storage
check_credential_storage() {
    log_info "Checking n8n credential storage..."
    
    DB_PATH="/data/.n8n/database.sqlite"
    
    if [ ! -f "$DB_PATH" ]; then
        log_error "n8n database not found at $DB_PATH"
        return 1
    fi
    
    # Check for PostgreSQL credentials
    CRED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity WHERE type='postgres';" 2>/dev/null || echo "0")
    log_info "Found $CRED_COUNT PostgreSQL credential(s)"
    
    if [ "$CRED_COUNT" -gt 0 ]; then
        # List credentials (without sensitive data)
        sqlite3 "$DB_PATH" "SELECT id, name FROM credentials_entity WHERE type='postgres';" 2>/dev/null | while IFS='|' read -r id name; do
            log_info "  - $name (ID: $id)"
            
            # Check if linked to project
            LINKED=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM shared_credentials WHERE credentialsId='$id';" 2>/dev/null || echo "0")
            if [ "$LINKED" -gt 0 ]; then
                log_success "    Linked to project"
            else
                log_warning "    Not linked to any project"
            fi
        done
    fi
    
    return 0
}

# Main execution
main() {
    log_info "=== PostgreSQL Connection Validation ==="
    log_info "Running from: $(hostname)"
    log_info "Container: $(cat /etc/hostname 2>/dev/null || echo 'unknown')"
    echo ""
    
    # Get credentials from environment or use defaults
    DB_HOST="${DB_HOST:-db}"
    DB_PORT="${DB_PORT:-5432}"
    DB_DATABASE="${DB_NAME:-aletheia}"
    DB_USER="${DB_USER:-aletheia}"
    DB_PASSWORD="${DB_PASSWORD:-aletheia_secure_pw_2024}"
    
    # Run tests
    test_network
    echo ""
    
    test_psql_connection "$DB_HOST" "$DB_PORT" "$DB_DATABASE" "$DB_USER" "$DB_PASSWORD"
    PSQL_RESULT=$?
    echo ""
    
    test_node_connection "$DB_HOST" "$DB_PORT" "$DB_DATABASE" "$DB_USER" "$DB_PASSWORD"
    NODE_RESULT=$?
    echo ""
    
    check_credential_storage
    echo ""
    
    # Summary
    log_info "=== Test Summary ==="
    
    if [ $NODE_RESULT -eq 0 ]; then
        log_success "Node.js connection test: PASSED"
        log_info "n8n should be able to connect to PostgreSQL"
    else
        log_error "Node.js connection test: FAILED"
        log_error "n8n will not be able to connect to PostgreSQL"
    fi
    
    if [ $PSQL_RESULT -eq 0 ]; then
        log_success "psql connection test: PASSED"
    elif [ $PSQL_RESULT -eq 2 ]; then
        log_warning "psql not available for testing"
    else
        log_error "psql connection test: FAILED"
    fi
    
    echo ""
    log_info "=== Recommendations ==="
    
    if [ $NODE_RESULT -ne 0 ]; then
        log_warning "1. Check if 'pg' npm package is installed in n8n container"
        log_warning "2. Verify network connectivity between containers"
        log_warning "3. Check PostgreSQL logs for authentication errors"
        log_warning "4. Ensure password doesn't contain problematic special characters"
    else
        log_info "Connection tests passed. If n8n still shows errors:"
        log_warning "1. Credential may need to be recreated in n8n UI"
        log_warning "2. Check if encryption key has changed"
        log_warning "3. Try testing credential directly in a workflow"
    fi
}

# Run main function
main "$@"