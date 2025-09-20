#!/bin/sh
# n8n Credential Setup Script
# This script creates/updates n8n credentials from environment variables
# It ensures credentials match the IDs expected by workflows

DB_PATH="/data/.n8n/database.sqlite"

echo "Setting up n8n credentials..."

# Wait for database to be ready
while [ ! -f "$DB_PATH" ]; do
    echo "  Waiting for n8n database..."
    sleep 2
done

# Get the project ID for the n8n user
PROJECT_ID=$(sqlite3 "$DB_PATH" "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1;" 2>/dev/null)

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID="personal-auto-setup-user"
    echo "  Using default project: $PROJECT_ID"
else
    echo "  Found project: $PROJECT_ID"
fi

# Function to create or update a credential
setup_credential() {
    local CRED_ID="$1"
    local CRED_NAME="$2"
    local CRED_TYPE="$3"
    local CRED_JSON="$4"
    
    # Check if credential exists
    EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity WHERE id='$CRED_ID';" 2>/dev/null || echo "0")
    
    if [ "$EXISTS" = "0" ]; then
        echo "  Creating credential: $CRED_NAME"
        
        # Create credential JSON file
        echo "[$CRED_JSON]" > /tmp/cred_${CRED_ID}.json
        
        # Import credential
        if n8n import:credentials --input=/tmp/cred_${CRED_ID}.json 2>&1 | grep -q "Successfully imported"; then
            # Link to project
            sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                                VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'));" 2>/dev/null
            echo "    ✓ Created and linked to project"
        else
            echo "    ⚠ Failed to create credential"
        fi
        
        rm -f /tmp/cred_${CRED_ID}.json
    else
        echo "  ✓ Credential exists: $CRED_NAME"
        
        # Ensure it's linked to the correct project
        sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
                            VALUES ('$CRED_ID', '$PROJECT_ID', 'credential:owner', datetime('now'), datetime('now'));" 2>/dev/null
    fi
}

# Setup PostgreSQL credentials
# Two IDs for backward compatibility with different workflows
echo "Configuring PostgreSQL credentials..."

# Primary PostgreSQL credential (used by some workflows)
POSTGRES_JSON='{
    "id": "PMs8mP0nYzWgEu40",
    "name": "Postgres Main",
    "type": "postgres",
    "data": {
        "host": "db",
        "port": 5432,
        "database": "'${DB_NAME:-aletheia}'",
        "user": "'${DB_USER:-aletheia}'",
        "password": "'${DB_PASSWORD:-aletheia_secure_pw_2024}'",
        "ssl": "disable"
    }
}'
setup_credential "PMs8mP0nYzWgEu40" "Postgres Main" "postgres" "$POSTGRES_JSON"

# Secondary PostgreSQL credential (used by Main Workflow)
POSTGRES_JSON2='{
    "id": "VLnn0kEGUTPNBqW5",
    "name": "Postgres account",
    "type": "postgres",
    "data": {
        "host": "db",
        "port": 5432,
        "database": "'${DB_NAME:-aletheia}'",
        "user": "'${DB_USER:-aletheia}'",
        "password": "'${DB_PASSWORD:-aletheia_secure_pw_2024}'",
        "ssl": "disable"
    }
}'
setup_credential "VLnn0kEGUTPNBqW5" "Postgres account" "postgres" "$POSTGRES_JSON2"

# Setup Anthropic credential if API key is provided
if [ -n "${ANTHROPIC_API_KEY}" ]; then
    echo "Configuring Anthropic credential..."
    
    ANTHROPIC_JSON='{
        "id": "eT6Unj67DfYj73os",
        "name": "Anthropic account",
        "type": "anthropicApi",
        "data": {
            "apiKey": "'${ANTHROPIC_API_KEY}'"
        }
    }'
    setup_credential "eT6Unj67DfYj73os" "Anthropic account" "anthropicApi" "$ANTHROPIC_JSON"
else
    echo "  ℹ No Anthropic API key provided (set ANTHROPIC_API_KEY in .env)"
fi

# Setup OpenAI credential if API key is provided
if [ -n "${OPENAI_API_KEY}" ]; then
    echo "Configuring OpenAI credential..."
    
    OPENAI_JSON='{
        "id": "openai-default",
        "name": "OpenAI account",
        "type": "openAiApi",
        "data": {
            "apiKey": "'${OPENAI_API_KEY}'"
        }
    }'
    setup_credential "openai-default" "OpenAI account" "openAiApi" "$OPENAI_JSON"
else
    echo "  ℹ No OpenAI API key provided (set OPENAI_API_KEY in .env)"
fi

echo "Credential setup complete!"