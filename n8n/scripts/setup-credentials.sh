#!/bin/sh
# Script to setup n8n credentials after n8n is running
# This uses n8n's import mechanism which properly handles encryption

set -e

echo "n8n Credentials Setup: Starting..."

# Wait for n8n to be ready
wait_for_n8n() {
    local max_attempts=30
    local attempt=0
    
    echo "Waiting for n8n API to be ready..."
    
    while [ $attempt -lt $max_attempts ]; do
        if wget -q --spider http://localhost:5678/healthz 2>/dev/null; then
            echo "n8n is ready!"
            return 0
        fi
        
        echo "  Waiting for n8n... (attempt $((attempt+1))/$max_attempts)"
        sleep 2
        attempt=$((attempt+1))
    done
    
    echo "ERROR: n8n did not start in time"
    return 1
}

# Function to create PostgreSQL credential
create_postgres_credential() {
    echo "Creating PostgreSQL credential..."
    
    # Get database connection details from environment
    local db_host="${DB_HOST:-db}"
    local db_port="${DB_PORT:-5432}"
    local db_name="${DB_NAME:-aletheia}"
    local db_user="${DB_USER:-aletheia}"
    local db_password="${DB_PASSWORD:-aletheia_secure_pw_2024}"
    
    # Create credential JSON
    cat > /tmp/postgres_cred.json <<EOF
{
  "name": "PostgreSQL - Aletheia",
  "type": "postgres",
  "data": {
    "host": "$db_host",
    "port": $db_port,
    "database": "$db_name",
    "user": "$db_user",
    "password": "$db_password",
    "ssl": "disable"
  }
}
EOF
    
    # Import credential using n8n CLI
    if n8n import:credentials --input=/tmp/postgres_cred.json 2>&1 | grep -q "Successfully imported"; then
        echo "  ✓ PostgreSQL credential created successfully"
    else
        echo "  ⚠ PostgreSQL credential may already exist or import failed"
    fi
    
    rm -f /tmp/postgres_cred.json
}

# Function to create Anthropic credential
create_anthropic_credential() {
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo "  ℹ No ANTHROPIC_API_KEY found, skipping Anthropic credential"
        return 0
    fi
    
    echo "Creating Anthropic AI credential..."
    
    # Create credential JSON
    cat > /tmp/anthropic_cred.json <<EOF
{
  "name": "Anthropic AI",
  "type": "anthropicApi",
  "data": {
    "apiKey": "$ANTHROPIC_API_KEY"
  }
}
EOF
    
    # Import credential using n8n CLI
    if n8n import:credentials --input=/tmp/anthropic_cred.json 2>&1 | grep -q "Successfully imported"; then
        echo "  ✓ Anthropic credential created successfully"
    else
        echo "  ⚠ Anthropic credential may already exist or import failed"
    fi
    
    rm -f /tmp/anthropic_cred.json
}

# Main execution
main() {
    # Wait for n8n to be ready
    if ! wait_for_n8n; then
        echo "ERROR: Cannot setup credentials - n8n is not running"
        exit 1
    fi
    
    # Check if we're inside the container
    if [ ! -f "/usr/local/lib/node_modules/n8n/package.json" ]; then
        echo "ERROR: This script must run inside the n8n container"
        exit 1
    fi
    
    echo "Setting up credentials..."
    
    # Create PostgreSQL credential
    create_postgres_credential
    
    # Create Anthropic credential if API key exists
    create_anthropic_credential
    
    # List credentials to verify
    echo ""
    echo "Current credentials:"
    sqlite3 /data/.n8n/database.sqlite "SELECT name, type FROM credentials_entity;" 2>/dev/null || echo "  Unable to list credentials"
    
    echo ""
    echo "Credentials setup complete!"
}

# Run main function
main