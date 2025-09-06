#!/bin/sh
# Optimized n8n startup for development
# This bypasses authentication and loads everything automatically

set -e

echo "🚀 n8n Development Startup"
echo "========================="

# Environment setup
export N8N_USER_MANAGEMENT_DISABLED=${N8N_USER_MANAGEMENT_DISABLED:-false}
export N8N_PUSH_BACKEND=websocket
export EXECUTIONS_PROCESS=main

# Function to wait for n8n database
wait_for_db() {
    echo "⏳ Waiting for n8n to initialize..."
    local max_attempts=60
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if [ -f "/data/.n8n/database.sqlite" ]; then
            # Check if basic tables exist
            if sqlite3 /data/.n8n/database.sqlite "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_entity';" 2>/dev/null | grep -q workflow_entity; then
                echo "✅ Database ready!"
                return 0
            fi
        fi
        sleep 2
        attempt=$((attempt+1))
        echo -n "."
    done
    
    echo "❌ Database initialization timeout"
    return 1
}

# Function to import workflows using n8n CLI
import_workflows_cli() {
    echo "📦 Importing workflows..."
    
    # n8n must be running to use import command
    for workflow_file in /workflows/*.json; do
        if [ -f "$workflow_file" ]; then
            basename=$(basename "$workflow_file")
            echo "  → Importing: $basename"
            
            # Try n8n CLI import first
            if n8n import:workflow --input="$workflow_file" 2>/dev/null; then
                echo "    ✓ Imported via CLI"
            else
                # Fallback to direct SQLite insert
                import_workflow_direct "$workflow_file"
            fi
        fi
    done
}

# Function to import workflow directly to SQLite
import_workflow_direct() {
    local workflow_file="$1"
    local basename=$(basename "$workflow_file")
    
    # Extract workflow name and clean JSON
    local workflow_name=$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$workflow_file" | head -1 | sed 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    
    if [ -z "$workflow_name" ]; then
        echo "    ⚠ Could not extract name from $basename"
        return 1
    fi
    
    # Check if already exists
    local exists=$(sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM workflow_entity WHERE name='$workflow_name'" 2>/dev/null || echo "0")
    
    if [ "$exists" -gt "0" ]; then
        echo "    ⚠ Already exists: $workflow_name"
        return 0
    fi
    
    # Parse JSON and extract components
    local nodes=$(jq -c '.nodes // []' "$workflow_file" 2>/dev/null || echo '[]')
    local connections=$(jq -c '.connections // {}' "$workflow_file" 2>/dev/null || echo '{}')
    local settings=$(jq -c '.settings // {}' "$workflow_file" 2>/dev/null || echo '{}')
    local staticData=$(jq -c '.staticData // {}' "$workflow_file" 2>/dev/null || echo '{}')
    
    # Generate ID
    local workflow_id=$(cat /proc/sys/kernel/random/uuid | tr -d '-')
    
    # Insert into database
    sqlite3 /data/.n8n/database.sqlite "INSERT INTO workflow_entity (
        id, name, active, nodes, connections, settings, staticData, 
        createdAt, updatedAt, versionId, pinData, triggerCount
    ) VALUES (
        '$workflow_id',
        '$(echo "$workflow_name" | sed "s/'/\\\\'/g")',
        1,
        '$(echo "$nodes" | sed "s/'/\\\\'/g")',
        '$(echo "$connections" | sed "s/'/\\\\'/g")',
        '$(echo "$settings" | sed "s/'/\\\\'/g")',
        '$(echo "$staticData" | sed "s/'/\\\\'/g")',
        datetime('now'),
        datetime('now'),
        '$(cat /proc/sys/kernel/random/uuid | tr -d '-')',
        '{}',
        0
    );" 2>/dev/null && echo "    ✓ Imported directly: $workflow_name" || echo "    ❌ Failed to import: $workflow_name"
}

# Function to setup owner account
setup_owner() {
    echo "👤 Setting up owner account..."
    
    # Check if owner exists
    local has_owner=$(sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM user WHERE role='global:owner'" 2>/dev/null || echo "0")
    
    if [ "$has_owner" -eq "0" ]; then
        # Create owner with simple credentials
        sqlite3 /data/.n8n/database.sqlite "INSERT INTO user (
            id, email, firstName, lastName, password, role, disabled, settings, createdAt, updatedAt
        ) VALUES (
            '$(cat /proc/sys/kernel/random/uuid | tr -d '-')',
            'velvetmoon222999@gmail.com',
            'Admin',
            'User',
            '\$2b\$10\$JtP/WWshmO5wNQ9frbf7Xu1BhRrv8ugRC/RqexJOiGv.Q8zWygHTe',
            'global:owner',
            0,
            '{}',
            datetime('now'),
            datetime('now')
        );"
        
        # Mark as setup
        sqlite3 /data/.n8n/database.sqlite "INSERT OR REPLACE INTO settings (key, value, loadOnStartup) VALUES ('userManagement.isInstanceOwnerSetUp', 'true', 1);"
        
        echo "  ✓ Owner created: velvetmoon222999@gmail.com / admin123"
    else
        echo "  ✓ Owner already exists"
    fi
}

# Function to create basic credentials
setup_credentials() {
    echo "🔑 Setting up credentials..."
    
    # Since n8n encrypts credentials, we need n8n running to import them
    # We'll create a marker for manual setup
    
    echo "  ℹ Credentials will be set up after n8n starts"
    
    # Create a script that can be run after n8n is up
    cat > /tmp/setup-creds.sh << 'EOF'
#!/bin/sh
sleep 5
echo "Setting up credentials..."

# PostgreSQL credential
cat > /tmp/pg.json << EOJSON
{
  "name": "PostgreSQL - Aletheia",
  "type": "postgres",
  "data": {
    "host": "${DB_HOST:-db}",
    "port": ${DB_PORT:-5432},
    "database": "${DB_NAME:-aletheia}",
    "user": "${DB_USER:-aletheia}",
    "password": "${DB_PASSWORD:-aletheia_secure_pw_2024}",
    "ssl": "disable"
  }
}
EOJSON

n8n import:credentials --input=/tmp/pg.json 2>/dev/null && echo "✓ PostgreSQL credential created"
rm -f /tmp/pg.json
EOF
    chmod +x /tmp/setup-creds.sh
}

# Main startup sequence
main() {
    echo "🔧 Running startup sequence..."
    
    # Start n8n in background
    n8n start &
    N8N_PID=$!
    
    # Wait for database
    if wait_for_db; then
        # Setup owner
        setup_owner
        
        # Import workflows
        import_workflows_cli
        
        # Activate all workflows
        echo "⚡ Activating workflows..."
        sqlite3 /data/.n8n/database.sqlite "UPDATE workflow_entity SET active=1 WHERE active=0;" 2>/dev/null
        
        # Setup credentials in background
        setup_credentials
        (/tmp/setup-creds.sh 2>/dev/null || true) &
        
        # Show summary
        echo ""
        echo "📊 Setup Summary"
        echo "==============="
        echo "Workflows: $(sqlite3 /data/.n8n/database.sqlite 'SELECT COUNT(*) FROM workflow_entity' 2>/dev/null || echo 0)"
        echo "Active: $(sqlite3 /data/.n8n/database.sqlite 'SELECT COUNT(*) FROM workflow_entity WHERE active=1' 2>/dev/null || echo 0)"
        echo "Users: $(sqlite3 /data/.n8n/database.sqlite 'SELECT COUNT(*) FROM user' 2>/dev/null || echo 0)"
        echo ""
        echo "✅ n8n is ready!"
        echo "📍 Access at: http://localhost:5678"
        echo "🔐 Login: velvetmoon222999@gmail.com / admin123"
        echo ""
    else
        echo "❌ Setup failed - database not ready"
    fi
    
    # Keep n8n running in foreground
    wait $N8N_PID
}

# Check if we have jq for JSON parsing
if ! command -v jq >/dev/null 2>&1; then
    echo "⚠ jq not found, installing..."
    apk add --no-cache jq
fi

# Run main
main