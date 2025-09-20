#!/bin/sh
# PostgreSQL Password Synchronization Script
# Ensures the database password matches the environment configuration

LOG_PREFIX="[Password Sync]"

# Color codes
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

# Get database credentials from environment
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_DATABASE="${DB_NAME:-aletheia}"
DB_USER="${DB_USER:-aletheia}"
DB_PASSWORD="${DB_PASSWORD:-aletheia_secure_pw_2024}"

log_info "Synchronizing PostgreSQL password..."
log_info "User: $DB_USER"
log_info "Database: $DB_DATABASE"

# Wait for database to be ready
MAX_WAIT=30
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if nc -zv $DB_HOST $DB_PORT 2>/dev/null; then
        log_success "Database is reachable"
        break
    fi
    log_info "Waiting for database... ($WAITED/$MAX_WAIT)"
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    log_warning "Database not reachable after ${MAX_WAIT} seconds"
    exit 1
fi

# Note: Password reset must be done from host or database container
# This script primarily verifies the connection
log_info "Note: Password sync should be run from host system"
log_info "This script will verify the current connection"

# Test the connection from n8n container
log_info "Verifying connection from n8n..."

# Create test script
cat > /tmp/verify_connection.js << EOF
const { Client } = require('pg');
const client = new Client({
    host: '$DB_HOST',
    port: $DB_PORT,
    database: '$DB_DATABASE',
    user: '$DB_USER',
    password: '$DB_PASSWORD',
    ssl: false,
    connectionTimeoutMillis: 5000
});

client.connect()
    .then(async () => {
        const res = await client.query('SELECT current_user, current_database()');
        console.log('SUCCESS:', res.rows[0]);
        await client.end();
        process.exit(0);
    })
    .catch(err => {
        console.error('FAILED:', err.message);
        process.exit(1);
    });
EOF

# Test from n8n's context
if cd /usr/local/lib/node_modules/n8n 2>/dev/null && node /tmp/verify_connection.js 2>/dev/null | grep -q "SUCCESS"; then
    log_success "Connection verified from n8n"
    rm -f /tmp/verify_connection.js
    exit 0
else
    log_warning "Connection test failed, credentials may need manual update in n8n UI"
    rm -f /tmp/verify_connection.js
    exit 1
fi