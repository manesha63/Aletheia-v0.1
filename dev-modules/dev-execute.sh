#!/bin/bash
# Workflow execution module
# Executes n8n workflows via their webhook endpoints discovered from JSON files

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

execute_workflow() {
    local workflow_name="$1"
    local test_data="$2"
    local workflow_file="workflow_json/${workflow_name}-workflow.json"

    # Check if workflow file exists
    if [ ! -f "$workflow_file" ]; then
        echo -e "${RED}❌ Workflow not found: $workflow_name${NC}"
        echo "Available workflows:"
        if [ -d "workflow_json" ]; then
            for wf_file in workflow_json/*-workflow.json; do
                if [ -f "$wf_file" ]; then
                    name=$(basename "$wf_file" .json | sed 's/-workflow$//')
                    echo "  - $name"
                fi
            done
        fi
        return 1
    fi

    # Extract webhook info from workflow JSON
    local webhook_id=$(jq -r '.[0].nodes[] | select(.type=="n8n-nodes-base.webhook") | .webhookId' "$workflow_file" 2>/dev/null)
    local http_method=$(jq -r '.[0].nodes[] | select(.type=="n8n-nodes-base.webhook") | .parameters.httpMethod' "$workflow_file" 2>/dev/null)

    if [ "$webhook_id" = "null" ] || [ -z "$webhook_id" ]; then
        echo -e "${RED}❌ No webhook trigger found in workflow: $workflow_name${NC}"
        echo "This workflow cannot be executed directly (no webhook trigger)"
        return 1
    fi

    # Build webhook URL
    local webhook_url="http://localhost:${N8N_PORT:-8100}/webhook/$webhook_id"

    # Prepare payload based on workflow patterns and user input
    local payload
    case "$workflow_name" in
        central)
            # Central workflow expects: {"sessionKey":"...", "message":"..."}
            if [ -n "$test_data" ] && [[ "$test_data" =~ ^\{ ]]; then
                # User provided JSON
                payload="$test_data"
            elif [ -n "$test_data" ]; then
                # User provided simple string
                payload="{\"sessionKey\":\"test-session\",\"message\":\"$test_data\"}"
            else
                # Default payload
                payload="{\"sessionKey\":\"test-session\",\"message\":\"Hello\"}"
            fi
            ;;
        search)
            # Search workflow expects: {"test":"..."}
            if [ -n "$test_data" ] && [[ "$test_data" =~ ^\{ ]]; then
                # User provided JSON - try to extract query field and map to test
                local query_value=$(echo "$test_data" | jq -r '.query // .test // .message // empty' 2>/dev/null)
                if [ -n "$query_value" ] && [ "$query_value" != "null" ]; then
                    payload="{\"test\":\"$query_value\"}"
                else
                    payload="$test_data"
                fi
            elif [ -n "$test_data" ]; then
                # User provided simple string
                payload="{\"test\":\"$test_data\"}"
            else
                # Default payload
                payload="{\"test\":\"Hello\"}"
            fi
            ;;
        *)
            # Generic approach for unknown workflows
            if [ -n "$test_data" ] && [[ "$test_data" =~ ^\{ ]]; then
                # User provided JSON
                payload="$test_data"
            elif [ -n "$test_data" ]; then
                # User provided simple string - use generic message format
                payload="{\"message\":\"$test_data\"}"
            else
                # Default payload
                payload="{\"message\":\"Hello\"}"
            fi
            ;;
    esac

    echo -e "${BLUE}🚀 Executing workflow: $workflow_name${NC}"
    echo "📡 Webhook: $webhook_url"
    echo "📦 Payload: $payload"
    echo ""

    # Execute via webhook
    local response=$(curl -s -w "\n%{http_code}" -X "$http_method" "$webhook_url" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}✅ Workflow executed successfully${NC}"
        echo ""
        echo "Response:"
        echo "$body" | head -20
        if [ $(echo "$body" | wc -l) -gt 20 ]; then
            echo "... (response truncated)"
        fi
    else
        echo -e "${RED}❌ Workflow execution failed (HTTP $http_code)${NC}"
        echo "Response: $body"
        echo ""
        echo -e "${YELLOW}Troubleshooting:${NC}"
        echo "  1. Check if workflow is active: ./dev n8n workflows list"
        echo "  2. Check n8n logs: ./dev n8n logs"
        echo "  3. Verify n8n is running: ./dev status"
        return 1
    fi
}

# Helper function to list available workflows
list_executable_workflows() {
    echo "Available executable workflows:"
    if [ -d "workflow_json" ]; then
        for workflow_file in workflow_json/*-workflow.json; do
            if [ -f "$workflow_file" ]; then
                local name=$(basename "$workflow_file" .json | sed 's/-workflow$//')
                local webhook_id=$(jq -r '.[0].nodes[] | select(.type=="n8n-nodes-base.webhook") | .webhookId' "$workflow_file" 2>/dev/null)
                if [ "$webhook_id" != "null" ] && [ -n "$webhook_id" ]; then
                    echo "  - $name"
                fi
            fi
        done
    else
        echo "  (no workflow_json directory found)"
    fi
}