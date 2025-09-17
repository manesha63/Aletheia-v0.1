#!/bin/bash

# Elasticsearch Integration Module for Dev CLI
# Provides direct PostgreSQL-Elasticsearch sync and search functionality

# Color definitions (if not already defined)
if [ -z "$RED" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    PURPLE='\033[0;35m'
    CYAN='\033[0;36m'
    NC='\033[0m' # No Color
fi

# Configuration
ES_SYNC_SCRIPT="court-processor/elasticsearch_sync.py"
ES_HOST="http://localhost:9200"
ES_INDEX="court-documents"

# Database configuration from environment
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-8200}"
DB_NAME="${DB_NAME:-aletheia}"
DB_USER="${DB_USER:-aletheia}"

# Load environment variables from .env if available
if [ -f ".env" ]; then
    # Load DB and ES configuration
    export $(grep -v '^#' .env | grep -E '(DB_|ELASTICSEARCH_|EMBEDDING_)' | xargs)
fi

# Main Elasticsearch command handler
handle_es_command() {
    local subcommand="$1"
    shift

    case "$subcommand" in
        setup)
            es_setup_index "$@"
            ;;
        sync)
            es_sync_documents "$@"
            ;;
        status)
            es_show_status "$@"
            ;;
        reset)
            es_reset_index "$@"
            ;;
        search)
            es_search_documents "$@"
            ;;
        health)
            es_health_check "$@"
            ;;
        count)
            es_document_count "$@"
            ;;
        *)
            es_show_help
            ;;
    esac
}

# Main search command handler
handle_search_command() {
    local query="$1"
    shift

    if [ -z "$query" ]; then
        echo -e "${RED}❌ Search query required${NC}"
        echo "Usage: ./dev search \"your query\" [options]"
        echo ""
        echo "Options:"
        echo "  --vector     Use vector similarity search"
        echo "  --hybrid     Use hybrid BM25 + vector search (default)"
        echo "  --bm25       Use only BM25 keyword search"
        echo "  --case       Filter by case number"
        echo "  --type       Filter by document type"
        echo "  --limit N    Limit results (default: 5)"
        echo ""
        echo "Examples:"
        echo "  ./dev search \"patent infringement\""
        echo "  ./dev search \"contract dispute\" --vector --limit 10"
        echo "  ./dev search \"trademark\" --case \"CV-2023\""
        return 1
    fi

    # Parse options
    local search_type="hybrid"
    local case_filter=""
    local type_filter=""
    local limit=5

    while [[ $# -gt 0 ]]; do
        case $1 in
            --vector)
                search_type="vector"
                shift
                ;;
            --hybrid)
                search_type="hybrid"
                shift
                ;;
            --bm25)
                search_type="bm25"
                shift
                ;;
            --case)
                case_filter="$2"
                shift 2
                ;;
            --type)
                type_filter="$2"
                shift 2
                ;;
            --limit)
                limit="$2"
                shift 2
                ;;
            *)
                echo -e "${YELLOW}⚠️  Unknown option: $1${NC}"
                shift
                ;;
        esac
    done

    es_perform_search "$query" "$search_type" "$case_filter" "$type_filter" "$limit"
}

# Setup Elasticsearch index
es_setup_index() {
    echo -e "${BLUE}🔧 Setting up Elasticsearch index...${NC}"

    if ! es_check_connectivity; then
        return 1
    fi

    # Run sync script to create index
    if ! es_run_sync_script "--create-index"; then
        echo -e "${RED}❌ Failed to create Elasticsearch index${NC}"
        return 1
    fi

    echo -e "${GREEN}✅ Elasticsearch index setup completed${NC}"
}

# Sync documents from PostgreSQL to Elasticsearch
es_sync_documents() {
    local sync_type="full"
    local batch_size=100

    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --incremental|-i)
                sync_type="incremental"
                shift
                ;;
            --batch-size)
                batch_size="$2"
                shift 2
                ;;
            --full|-f)
                sync_type="full"
                shift
                ;;
            *)
                echo -e "${YELLOW}⚠️  Unknown sync option: $1${NC}"
                shift
                ;;
        esac
    done

    echo -e "${BLUE}🔄 Starting ${sync_type} document sync...${NC}"

    if ! es_check_connectivity; then
        return 1
    fi

    # Run appropriate sync command
    local sync_args="--sync-all --batch-size $batch_size"
    if [ "$sync_type" = "incremental" ]; then
        echo -e "${YELLOW}ℹ️  Incremental sync not yet implemented, running full sync${NC}"
    fi

    if ! es_run_sync_script "$sync_args"; then
        echo -e "${RED}❌ Document sync failed${NC}"
        return 1
    fi

    # Show final status
    echo -e "${GREEN}✅ Document sync completed${NC}"
    es_show_status --quiet
}

# Show Elasticsearch status
es_show_status() {
    local quiet=false
    if [ "$1" = "--quiet" ]; then
        quiet=true
    fi

    if [ "$quiet" = false ]; then
        echo -e "${BLUE}📊 Elasticsearch Status${NC}"
        echo -e "${BLUE}========================${NC}"
    fi

    if ! es_check_connectivity; then
        return 1
    fi

    # Run status command
    if es_run_sync_script "--status" 2>/dev/null; then
        if [ "$quiet" = false ]; then
            echo ""
            echo -e "${GREEN}✅ Status check completed${NC}"
        fi
    else
        echo -e "${RED}❌ Failed to get status${NC}"
        return 1
    fi
}

# Reset Elasticsearch index
es_reset_index() {
    echo -e "${YELLOW}⚠️  This will delete all documents in the Elasticsearch index${NC}"
    read -p "Are you sure you want to continue? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}ℹ️  Operation cancelled${NC}"
        return 0
    fi

    echo -e "${BLUE}🗑️  Resetting Elasticsearch index...${NC}"

    if ! es_check_connectivity; then
        return 1
    fi

    # Delete index
    local response=$(curl -s -X DELETE "$ES_HOST/$ES_INDEX" 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Index deleted${NC}"
    else
        echo -e "${YELLOW}⚠️  Index may not have existed${NC}"
    fi

    # Recreate index
    if es_setup_index; then
        echo -e "${GREEN}✅ Index reset completed${NC}"
    else
        echo -e "${RED}❌ Failed to recreate index${NC}"
        return 1
    fi
}

# Perform search operation
es_perform_search() {
    local query="$1"
    local search_type="$2"
    local case_filter="$3"
    local type_filter="$4"
    local limit="$5"

    echo -e "${BLUE}🔍 Searching for: \"$query\"${NC}"
    echo -e "${BLUE}Search type: $search_type, Limit: $limit${NC}"

    if ! es_check_connectivity; then
        return 1
    fi

    # Build search query
    local search_query=""
    local filters=""

    # Add case filter
    if [ -n "$case_filter" ]; then
        filters="$filters,{\"wildcard\":{\"case_number\":\"*$case_filter*\"}}"
    fi

    # Add type filter
    if [ -n "$type_filter" ]; then
        filters="$filters,{\"term\":{\"document_type\":\"$type_filter\"}}"
    fi

    # Remove leading comma
    filters="${filters#,}"

    # Build query based on search type
    case "$search_type" in
        "bm25")
            search_query="{\"query\":{\"bool\":{\"must\":[{\"match\":{\"content\":\"$query\"}}]"
            if [ -n "$filters" ]; then
                search_query="$search_query,\"filter\":[$filters]"
            fi
            search_query="$search_query}},\"size\":$limit}"
            ;;
        "vector")
            echo -e "${YELLOW}⚠️  Vector search requires embedding generation - using BM25 for now${NC}"
            search_query="{\"query\":{\"match\":{\"content\":\"$query\"}},\"size\":$limit}"
            ;;
        "hybrid"|*)
            search_query="{\"query\":{\"match\":{\"content\":\"$query\"}},\"size\":$limit}"
            ;;
    esac

    # Execute search
    local response=$(curl -s -X POST "$ES_HOST/$ES_INDEX/_search" \
        -H "Content-Type: application/json" \
        -d "$search_query" 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Search request failed${NC}"
        return 1
    fi

    # Parse and display results
    es_display_search_results "$response" "$query"
}

# Display search results
es_display_search_results() {
    local response="$1"
    local query="$2"

    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        echo -e "${YELLOW}⚠️  jq not available, showing raw response${NC}"
        echo "$response"
        return 0
    fi

    # Parse results with jq
    local total=$(echo "$response" | jq -r '.hits.total.value // 0' 2>/dev/null)
    local hits=$(echo "$response" | jq -r '.hits.hits[]' 2>/dev/null)

    echo ""
    echo -e "${GREEN}📄 Found $total documents${NC}"
    echo -e "${GREEN}================================${NC}"

    if [ "$total" = "0" ]; then
        echo -e "${YELLOW}No documents found matching your query${NC}"
        return 0
    fi

    # Display each result
    local count=0
    echo "$response" | jq -r '.hits.hits[]' 2>/dev/null | while read -r hit; do
        count=$((count + 1))

        local doc_id=$(echo "$hit" | jq -r '._source.id // "N/A"' 2>/dev/null)
        local case_number=$(echo "$hit" | jq -r '._source.case_number // "N/A"' 2>/dev/null)
        local case_name=$(echo "$hit" | jq -r '._source.case_name // "N/A"' 2>/dev/null)
        local doc_type=$(echo "$hit" | jq -r '._source.document_type // "N/A"' 2>/dev/null)
        local score=$(echo "$hit" | jq -r '._score // "N/A"' 2>/dev/null)
        local content=$(echo "$hit" | jq -r '._source.content // ""' 2>/dev/null)

        echo -e "${CYAN}[$count] Document ID: $doc_id (Score: $score)${NC}"
        echo -e "${BLUE}Case: $case_number${NC}"
        if [ "$case_name" != "N/A" ] && [ "$case_name" != "null" ]; then
            echo -e "${BLUE}Name: $case_name${NC}"
        fi
        echo -e "${BLUE}Type: $doc_type${NC}"

        # Show content preview (first 200 characters)
        if [ -n "$content" ] && [ "$content" != "null" ]; then
            local preview=$(echo "$content" | head -c 200 | tr '\n' ' ')
            echo -e "${PURPLE}Preview: $preview...${NC}"
        fi
        echo ""
    done
}

# Check Elasticsearch connectivity
es_check_connectivity() {
    if ! curl -s "$ES_HOST" >/dev/null 2>&1; then
        echo -e "${RED}❌ Cannot connect to Elasticsearch at $ES_HOST${NC}"
        echo -e "${YELLOW}💡 Make sure Elasticsearch is running${NC}"
        return 1
    fi
    return 0
}

# Health check
es_health_check() {
    echo -e "${BLUE}🏥 Elasticsearch Health Check${NC}"
    echo -e "${BLUE}==============================${NC}"

    if ! es_check_connectivity; then
        return 1
    fi

    # Get cluster health
    local health=$(curl -s "$ES_HOST/_cluster/health" 2>/dev/null)
    if [ $? -eq 0 ]; then
        if command -v jq &> /dev/null; then
            local status=$(echo "$health" | jq -r '.status')
            local nodes=$(echo "$health" | jq -r '.number_of_nodes')
            local indices=$(echo "$health" | jq -r '.active_primary_shards')

            echo -e "${GREEN}Cluster Status: $status${NC}"
            echo -e "${GREEN}Nodes: $nodes${NC}"
            echo -e "${GREEN}Active Shards: $indices${NC}"
        else
            echo "$health"
        fi
    fi

    # Check index status
    es_document_count --quiet
}

# Get document count
es_document_count() {
    local quiet=false
    if [ "$1" = "--quiet" ]; then
        quiet=true
    fi

    if [ "$quiet" = false ]; then
        echo -e "${BLUE}📊 Document Count${NC}"
        echo -e "${BLUE}==================${NC}"
    fi

    if ! es_check_connectivity; then
        return 1
    fi

    local count_response=$(curl -s "$ES_HOST/$ES_INDEX/_count" 2>/dev/null)
    if [ $? -eq 0 ]; then
        if command -v jq &> /dev/null; then
            local count=$(echo "$count_response" | jq -r '.count // 0')
            echo -e "${GREEN}Documents in Elasticsearch: $count${NC}"
        else
            echo "$count_response"
        fi
    else
        echo -e "${RED}❌ Failed to get document count${NC}"
        return 1
    fi
}

# Run sync script with proper environment
es_run_sync_script() {
    local args="$1"

    if [ ! -f "$ES_SYNC_SCRIPT" ]; then
        echo -e "${RED}❌ Sync script not found: $ES_SYNC_SCRIPT${NC}"
        return 1
    fi

    # Set environment variables
    export DB_HOST="$DB_HOST"
    export DB_PORT="$DB_PORT"
    export DB_NAME="$DB_NAME"
    export DB_USER="$DB_USER"
    export ELASTICSEARCH_HOST="$ES_HOST"
    export ELASTICSEARCH_INDEX="$ES_INDEX"

    # Run the sync script
    cd court-processor 2>/dev/null || {
        echo -e "${RED}❌ Cannot access court-processor directory${NC}"
        return 1
    }

    python3 elasticsearch_sync.py $args
    local exit_code=$?

    cd - >/dev/null
    return $exit_code
}

# Show help for Elasticsearch commands
es_show_help() {
    echo -e "${BLUE}Elasticsearch Commands${NC}"
    echo -e "${BLUE}======================${NC}"
    echo ""
    echo -e "${GREEN}Management:${NC}"
    echo "  ./dev es setup           Create Elasticsearch index with proper mapping"
    echo "  ./dev es sync            Sync all documents from PostgreSQL"
    echo "  ./dev es sync --incremental  Sync only new/updated documents"
    echo "  ./dev es status          Show sync status and document counts"
    echo "  ./dev es reset           Delete and recreate index"
    echo "  ./dev es health          Show Elasticsearch cluster health"
    echo "  ./dev es count           Show document count"
    echo ""
    echo -e "${GREEN}Search:${NC}"
    echo "  ./dev search \"query\"      Search documents (hybrid search)"
    echo "  ./dev search \"query\" --vector    Vector similarity search"
    echo "  ./dev search \"query\" --bm25      Keyword search only"
    echo "  ./dev search \"query\" --case NUM  Filter by case number"
    echo "  ./dev search \"query\" --type TYPE Filter by document type"
    echo "  ./dev search \"query\" --limit N   Limit results (default: 5)"
    echo ""
    echo -e "${GREEN}Examples:${NC}"
    echo "  ./dev es setup"
    echo "  ./dev es sync --batch-size 50"
    echo "  ./dev search \"patent infringement\""
    echo "  ./dev search \"trademark\" --case \"CV-2023\" --limit 10"
    echo ""
}

# Show help for search commands
search_show_help() {
    echo -e "${BLUE}Search Commands${NC}"
    echo -e "${BLUE}===============${NC}"
    echo ""
    echo "Usage: ./dev search \"query\" [options]"
    echo ""
    echo -e "${GREEN}Search Types:${NC}"
    echo "  --hybrid     BM25 + vector search (default)"
    echo "  --vector     Vector similarity search only"
    echo "  --bm25       BM25 keyword search only"
    echo ""
    echo -e "${GREEN}Filters:${NC}"
    echo "  --case NUM   Filter by case number"
    echo "  --type TYPE  Filter by document type"
    echo "  --limit N    Limit results (default: 5)"
    echo ""
    echo -e "${GREEN}Examples:${NC}"
    echo "  ./dev search \"patent law\""
    echo "  ./dev search \"contract dispute\" --vector"
    echo "  ./dev search \"trademark\" --case \"CV-2023\""
    echo "  ./dev search \"copyright\" --type \"opinion\" --limit 10"
    echo ""
}