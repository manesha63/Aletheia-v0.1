#!/bin/sh
# Validate that webhook access is working without manual login
# This script tests if the authentication bypass is functioning correctly

set -e

# Configuration
N8N_URL="http://localhost:5678"
WEBHOOK_ID="${N8N_WEBHOOK_ID:-c188c31c-1c45-4118-9ece-5b6057ab5177}"
API_KEY_FILE="/data/.n8n/.api-key"

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[webhook-test]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[webhook-test]${NC} ✓ $1"
}

log_error() {
    echo -e "${RED}[webhook-test]${NC} ✗ $1"
}

# Test webhook access
test_webhook() {
    local webhook_url="$N8N_URL/webhook/$WEBHOOK_ID"
    local test_payload='{"test":true,"message":"Authentication bypass test"}'
    
    log_info "Testing webhook endpoint: $webhook_url"
    
    # First try without authentication
    log_info "Attempt 1: Testing without authentication..."
    response=$(curl -s -w "\n%{http_code}" -X POST "$webhook_url" \
        -H "Content-Type: application/json" \
        -d "$test_payload" 2>/dev/null || echo "000")
    
    http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" = "200" ]; then
        log_success "Webhook accessible without authentication!"
        return 0
    elif [ "$http_code" = "404" ]; then
        log_info "Webhook requires authentication (404)"
    else
        log_info "Received HTTP $http_code"
    fi
    
    # Try with API key if available
    if [ -f "$API_KEY_FILE" ]; then
        API_KEY=$(cat "$API_KEY_FILE")
        
        if [ -n "$API_KEY" ]; then
            log_info "Attempt 2: Testing with API key..."
            response=$(curl -s -w "\n%{http_code}" -X POST "$webhook_url" \
                -H "Content-Type: application/json" \
                -H "X-N8N-API-KEY: $API_KEY" \
                -d "$test_payload" 2>/dev/null || echo "000")
            
            http_code=$(echo "$response" | tail -n1)
            
            if [ "$http_code" = "200" ]; then
                log_success "Webhook accessible with API key!"
                log_info "API Key: $API_KEY"
                return 0
            else
                log_error "Webhook still not accessible (HTTP $http_code)"
                return 1
            fi
        fi
    else
        log_error "No API key file found at $API_KEY_FILE"
        return 1
    fi
    
    return 1
}

# Main execution
main() {
    log_info "=== Webhook Access Validation ==="
    
    if test_webhook; then
        log_success "Authentication bypass is working!"
        log_info "The webhook can be accessed programmatically"
        exit 0
    else
        log_error "Authentication bypass not working"
        log_info "Manual login may still be required"
        exit 1
    fi
}

# Run
main "$@"