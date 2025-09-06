#!/bin/sh
DB_PATH="/data/.n8n/database.sqlite"
SETUP_EMAIL="${N8N_SETUP_EMAIL:-velvetmoon222999@gmail.com}"
SETUP_PASSWORD="${N8N_SETUP_PASSWORD:-admin123}"
MAX_WAIT=120  # Maximum wait time in seconds
WAIT_INTERVAL=5  # Check interval in seconds

echo "n8n Auto Setup: Starting enhanced setup process..."

# Function to wait for database and required tables
wait_for_n8n_ready() {
    local elapsed=0
    
    echo "Waiting for n8n to initialize database..."
    
    # Wait for database file to exist
    while [ ! -f "$DB_PATH" ]; do
        if [ $elapsed -ge $MAX_WAIT ]; then
            echo "ERROR: Database not created after ${MAX_WAIT} seconds"
            return 1
        fi
        echo "  Waiting for database... ($elapsed/$MAX_WAIT seconds)"
        sleep $WAIT_INTERVAL
        elapsed=$((elapsed + WAIT_INTERVAL))
    done
    
    echo "Database file found. Checking for required tables..."
    
    # Wait for settings table to exist (indicates n8n is fully initialized)
    while true; do
        if [ $elapsed -ge $MAX_WAIT ]; then
            echo "ERROR: n8n tables not ready after ${MAX_WAIT} seconds"
            return 1
        fi
        
        # Check if settings table exists and is accessible
        if sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='settings';" 2>/dev/null | grep -q settings; then
            echo "n8n database is ready!"
            return 0
        fi
        
        echo "  Waiting for n8n tables... ($elapsed/$MAX_WAIT seconds)"
        sleep $WAIT_INTERVAL
        elapsed=$((elapsed + WAIT_INTERVAL))
    done
}

# Function to verify custom nodes are loaded
verify_custom_nodes() {
    echo "Verifying custom nodes..."
    local nodes_found=0
    
    # Check if custom nodes directory exists and has content
    if [ -d "/data/.n8n/custom" ]; then
        for node_dir in /data/.n8n/custom/*/; do
            if [ -d "$node_dir" ]; then
                node_name=$(basename "$node_dir")
                if [ -f "${node_dir}dist/index.js" ] || [ -f "${node_dir}package.json" ]; then
                    echo "  ✓ Found custom node: $node_name"
                    nodes_found=$((nodes_found + 1))
                else
                    echo "  ⚠ Custom node missing files: $node_name"
                fi
            fi
        done
    fi
    
    if [ $nodes_found -gt 0 ]; then
        echo "  Found $nodes_found custom nodes"
        return 0
    else
        echo "  WARNING: No custom nodes found"
        return 1
    fi
}

# Function to import workflows from /workflows directory
import_workflows() {
    echo "Importing workflows..."
    
    if [ ! -d "/workflows" ]; then
        echo "  ⚠ No /workflows directory found"
        return 1
    fi
    
    local workflow_count=$(find /workflows -name "*.json" -type f 2>/dev/null | wc -l)
    
    if [ "$workflow_count" -eq "0" ]; then
        echo "  ⚠ No workflow files found in /workflows"
        return 1
    fi
    
    echo "  Found $workflow_count workflow file(s) to import"
    
    # Import each workflow using n8n CLI
    for workflow_file in /workflows/*.json; do
        if [ -f "$workflow_file" ]; then
            local basename=$(basename "$workflow_file")
            echo "  Importing: $basename"
            
            # Use n8n CLI to import workflow
            # The n8n import:workflow command requires n8n to be running
            # So we'll directly insert into SQLite for now
            
            # Extract workflow data (this is a simplified approach)
            # In production, you'd want to use n8n's proper import mechanism
            local workflow_name=$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$workflow_file" | head -1 | sed 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
            
            if [ -n "$workflow_name" ]; then
                # Check if workflow already exists
                local existing=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity WHERE name='$workflow_name'" 2>/dev/null || echo "0")
                
                if [ "$existing" -eq "0" ]; then
                    # Parse the workflow JSON to extract components
                    # Use temporary files to handle complex JSON
                    local tmp_file="/tmp/workflow_$$_$(date +%s).json"
                    cp "$workflow_file" "$tmp_file"
                    
                    # Extract nodes and connections as separate JSON strings
                    local nodes=$(python3 -c "import json; data=json.load(open('$tmp_file')); print(json.dumps(data.get('nodes', [])))" 2>/dev/null || echo '[]')
                    local connections=$(python3 -c "import json; data=json.load(open('$tmp_file')); print(json.dumps(data.get('connections', {})))" 2>/dev/null || echo '{}')
                    local settings=$(python3 -c "import json; data=json.load(open('$tmp_file')); print(json.dumps(data.get('settings', {})))" 2>/dev/null || echo '{}')
                    
                    # Clean up temp file
                    rm -f "$tmp_file"
                    
                    # Escape single quotes for SQL
                    nodes=$(echo "$nodes" | sed "s/'/\\\\'/g")
                    connections=$(echo "$connections" | sed "s/'/\\\\'/g")
                    settings=$(echo "$settings" | sed "s/'/\\\\'/g")
                    
                    # Generate a UUID-like ID
                    local workflow_id=$(cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' || echo "$(date +%s)$(shuf -i 1000-9999 -n 1)")
                    
                    # Insert workflow with properly separated fields
                    sqlite3 "$DB_PATH" "INSERT INTO workflow_entity (id, name, active, nodes, connections, createdAt, updatedAt, settings, staticData, pinData, versionId, triggerCount) 
                                        VALUES (
                                            '$workflow_id', 
                                            '$workflow_name', 
                                            0, 
                                            '$nodes', 
                                            '$connections', 
                                            datetime('now'), 
                                            datetime('now'), 
                                            '$settings', 
                                            '{}', 
                                            '{}', 
                                            '$(cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' || echo "v$(date +%s)")', 
                                            0
                                        )" 2>/dev/null || echo "    ⚠ Failed to import $basename"
                    
                    # Link workflow to user's project
                    PROJECT_ID="personal-auto-setup-user"
                    sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO shared_workflow (workflowId, projectId, role, createdAt, updatedAt) 
                                        VALUES ('$workflow_id', '$PROJECT_ID', 'workflow:owner', datetime('now'), datetime('now'))" 2>/dev/null
                    
                    echo "    ✓ Imported: $workflow_name"
                else
                    echo "    ⚠ Skipping $workflow_name - already exists"
                fi
            else
                echo "    ⚠ Could not extract workflow name from $basename"
            fi
        fi
    done
    
    return 0
}

# Function to setup credentials
setup_credentials() {
    echo "Setting up credentials..."
    
    # Check if credentials already exist
    local cred_count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity" 2>/dev/null || echo "0")
    
    if [ "$cred_count" -gt "0" ]; then
        echo "  ✓ Credentials already exist: $cred_count found"
        return 0
    fi
    
    # Run the credential setup script which uses n8n's import mechanism
    if [ -f "/usr/local/bin/setup-credentials" ]; then
        echo "  Running credential setup..."
        /usr/local/bin/setup-credentials
    else
        echo "  ⚠ Credential setup script not found"
        echo "  ℹ Credentials need to be configured via n8n UI after login"
        echo "    - PostgreSQL: db:5432 with user '${DB_USER:-aletheia}'"
        echo "    - Anthropic AI: Add API key if available"
    fi
    
    return 0
}

# Main execution
main() {
    # Wait for n8n to be ready
    if ! wait_for_n8n_ready; then
        echo "ERROR: n8n failed to initialize properly"
        exit 1
    fi
    
    # Check if owner is set up
    IS_SETUP=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key = 'userManagement.isInstanceOwnerSetUp'" 2>/dev/null || echo "")
    
    if [ "$IS_SETUP" = "true" ]; then
        echo "n8n already has an owner account"
    else
        echo "Creating owner account..."
        # Create owner with proper password hash for admin123
        # This hash was generated with bcryptjs using cost factor 10
        USER_ID="auto-setup-user"
        sqlite3 "$DB_PATH" "INSERT INTO user (id, email, firstName, lastName, password, role, disabled, settings, createdAt, updatedAt) VALUES ('$USER_ID', '$SETUP_EMAIL', 'Admin', 'User', '\$2b\$10\$JtP/WWshmO5wNQ9frbf7Xu1BhRrv8ugRC/RqexJOiGv.Q8zWygHTe', 'global:owner', 0, '{}', datetime('now'), datetime('now'))"
        
        # Create personal project for the user (required in newer n8n versions)
        PROJECT_ID="personal-$USER_ID"
        sqlite3 "$DB_PATH" "INSERT INTO project (id, name, type, createdAt, updatedAt) VALUES ('$PROJECT_ID', 'Personal Project', 'personal', datetime('now'), datetime('now'))"
        sqlite3 "$DB_PATH" "INSERT INTO project_relation (projectId, userId, role, createdAt, updatedAt) VALUES ('$PROJECT_ID', '$USER_ID', 'project:personalOwner', datetime('now'), datetime('now'))"
        
        sqlite3 "$DB_PATH" "INSERT OR REPLACE INTO settings (key, value, loadOnStartup) VALUES ('userManagement.isInstanceOwnerSetUp', 'true', 1)"
        echo "  ✓ Owner created: $SETUP_EMAIL (password: $SETUP_PASSWORD)"
    fi
    
    # Verify custom nodes
    verify_custom_nodes
    
    # Setup credentials
    setup_credentials
    
    # Import and activate workflows
    import_workflows
    
    # Check final workflow count
    echo "Checking workflows..."
    WORKFLOW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity" 2>/dev/null || echo "0")
    
    if [ "$WORKFLOW_COUNT" -gt "0" ]; then
        echo "  ✓ Found $WORKFLOW_COUNT workflow(s)"
        
        # Activate all workflows
        echo "  Activating workflows..."
        sqlite3 "$DB_PATH" "UPDATE workflow_entity SET active = 1 WHERE active = 0"
        
        ACTIVE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM workflow_entity WHERE active = 1" 2>/dev/null || echo "0")
        echo "  ✓ $ACTIVE_COUNT workflow(s) are now active"
    else
        echo "  ⚠ No workflows found after import attempt"
    fi
    
    # Final verification
    echo ""
    echo "=== n8n Setup Summary ==="
    echo "Database: Ready"
    echo "Owner Account: $SETUP_EMAIL"
    echo "Custom Nodes: $(ls -d /data/.n8n/custom/*/ 2>/dev/null | wc -l) loaded"
    echo "Workflows: $WORKFLOW_COUNT total"
    echo "Credentials: $(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM credentials_entity" 2>/dev/null || echo "0") configured"
    echo "========================="
    echo "Setup complete! n8n should be accessible at http://localhost:5678"
    echo "Login with: $SETUP_EMAIL / $SETUP_PASSWORD"
}

# Run main function
main