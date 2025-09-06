# n8n Hardcoded IDs Breaking Workflow Portability

## Problem Summary
Webhook IDs, workflow IDs, and credential IDs are hardcoded throughout the system, causing workflows to break when reimported or when containers are rebuilt. The system expects specific IDs that change on every import.

## Current Behavior
1. Webhook test expects workflow ID `AaDB6QDmQOyP1E25` (hardcoded)
2. Central workflow has new ID `49BDaNi8B8dFKpHT` after import
3. Test fails with: `"Could not find workflow with id \"AaDB6QDmQOyP1E25\""`
4. Credentials reference specific IDs that may not exist

## Root Causes

### 1. Hardcoded Webhook ID in Test Script
```bash
# dev-modules/dev-n8n.sh line 1553
webhook_url="http://localhost:${N8N_PORT:-8100}/webhook/${N8N_WEBHOOK_ID}"
# N8N_WEBHOOK_ID is hardcoded in .env as c188c31c-1c45-4118-9ece-5b6057ab5177
```

### 2. Workflow Files Contain Fixed IDs
```json
// central-workflow.json
"webhookId": "c188c31c-1c45-4118-9ece-5b6057ab5177"  // Hardcoded
"credentials": {
    "postgres": {
        "id": "VLnn0kEGUTPNBqW5",  // Hardcoded credential ID
        "name": "Postgres account"
    }
}
```

### 3. Credential Scripts Use Fixed IDs
```bash
# manage-credentials.sh
setup_credential "VLnn0kEGUTPNBqW5" "Postgres account"  # Fixed ID
setup_credential "eT6Unj67DfYj73os" "Anthropic account"  # Fixed ID
```

## Evidence
```bash
# Test fails due to wrong workflow ID
./dev n8n test webhook
# Response: {"code":404,"message":"Could not find workflow with id \"AaDB6QDmQOyP1E25\""}

# But workflow exists with different ID
docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
  "SELECT id, name FROM workflow_entity WHERE name='central';"
# Output: 49BDaNi8B8dFKpHT|central
```

## Proposed Solution

### 1. Use Dynamic Webhook Discovery
```bash
# Instead of hardcoded webhook ID, find it dynamically
WEBHOOK_PATH=$(docker exec $CONTAINER sqlite3 /data/.n8n/database.sqlite \
  "SELECT json_extract(nodes, '$[0].parameters.path') 
   FROM workflow_entity 
   WHERE name='central' 
   AND json_extract(nodes, '$[0].type') LIKE '%webhook%'")
```

### 2. Reference Credentials by Name
```javascript
// In workflow JSON
"credentials": {
    "postgres": {
        "name": "Postgres account"  // Use name only, let n8n resolve ID
    }
}
```

### 3. Import with Stable IDs
```bash
# Force specific IDs during import
n8n import:workflow --input=workflow.json --id=stable-workflow-id
n8n import:credentials --input=creds.json --update-existing
```

### 4. Update Test Command
```bash
# dev-n8n.sh test function
test_webhook() {
    # Get actual webhook URL from database
    WEBHOOK_INFO=$(docker exec $CONTAINER sqlite3 /data/.n8n/database.sqlite \
      "SELECT id, json_extract(nodes, '$') FROM workflow_entity WHERE name='central'")
    
    # Extract webhook path from workflow nodes
    WEBHOOK_PATH=$(echo "$WEBHOOK_INFO" | parse_webhook_path)
    
    # Use discovered path
    curl "http://localhost:${N8N_PORT}/webhook/${WEBHOOK_PATH}"
}
```

## Implementation Steps

### Step 1: Create ID Resolution Functions
```bash
# n8n/scripts/utils.sh
get_workflow_id() {
    local name="$1"
    sqlite3 $DB_PATH "SELECT id FROM workflow_entity WHERE name='$name' LIMIT 1"
}

get_credential_id() {
    local name="$1"
    local type="$2"
    sqlite3 $DB_PATH "SELECT id FROM credentials_entity WHERE name='$name' AND type='$type' LIMIT 1"
}

get_webhook_path() {
    local workflow_name="$1"
    # Parse webhook path from workflow nodes JSON
}
```

### Step 2: Update Workflow Export/Import
- Strip IDs from exported workflows
- Let n8n generate new IDs on import
- Map by name instead of ID

### Step 3: Fix Test Command
- Remove hardcoded webhook ID from .env
- Discover webhook dynamically
- Test by workflow name, not ID

## Testing
1. Delete all workflows and credentials
2. Import fresh from repository
3. Test should find webhook dynamically
4. Rebuild container
5. Test should still work with new IDs

## Impact
- **High Priority**: Breaks workflow portability
- **Development**: Cannot share workflows between environments
- **Testing**: Tests fail after every rebuild

## Files Affected
- `.env` - Remove `N8N_WEBHOOK_ID`
- `dev-modules/dev-n8n.sh` - Dynamic webhook discovery
- `n8n/scripts/manage-credentials.sh` - Reference by name
- `workflow_json/central-workflow.json` - Remove hardcoded IDs
- All import scripts - Handle ID mapping

## Related Issues
- Workflow persistence (workflows not saved to repository)
- Multiple import scripts causing duplicates
- Credential corruption from logging issues