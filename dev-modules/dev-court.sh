#!/bin/bash

# ============================================================================
# Court Processor Integration Module
# ============================================================================
# Provides dev CLI integration with the court-processor standalone CLI
# Maintains separation of concerns by delegating to the court-processor container

# Validate court-processor is available
validate_court_processor() {
    if ! $DOCKER_COMPOSE ps court-processor | grep -q "Up"; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"error","message":"Court processor service not running"}'
        else
            echo -e "${RED}❌ Court processor service is not running${NC}"
            echo "Start it with: ./dev up"
        fi
        return $EXIT_SERVICE_UNAVAILABLE
    fi
}

# Execute court-processor CLI command
execute_court_cli() {
    local cmd="$1"
    shift
    local args="$*"
    
    # Validate service is running
    if ! validate_court_processor; then
        return $?
    fi
    
    # Execute the command in the court-processor container
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        # For JSON output, capture and format appropriately
        local result
        result=$($DOCKER_COMPOSE exec -T court-processor python cli.py $cmd $args 2>&1)
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            # Check if output is already JSON
            if echo "$result" | jq . >/dev/null 2>&1; then
                echo "$result"
            else
                echo "{\"status\":\"success\",\"output\":$(echo "$result" | jq -R -s .)}"
            fi
        else
            echo "{\"status\":\"error\",\"message\":$(echo "$result" | jq -R -s .),\"exit_code\":$exit_code}"
        fi
        return $exit_code
    else
        # For normal output, pass through directly
        $DOCKER_COMPOSE exec court-processor python cli.py $cmd $args
        return $?
    fi
}

# Court processor command router
handle_court_command() {
    local subcommand="$1"
    shift
    
    case "$subcommand" in
        analyze)
            handle_court_analyze_command "$@"
            ;;
        collect)
            handle_court_collect_command "$@"
            ;;
        data)
            handle_court_data_command "$@"
            ;;
        search)
            handle_court_search_command "$@"
            ;;
        pipeline)
            handle_court_pipeline_command "$@"
            ;;
        status)
            court_status
            ;;
        api)
            court_api_examples "$@"
            ;;
        help|--help|-h|"")
            court_help
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown court command: $subcommand\"}"
            else
                echo -e "${RED}Unknown court command: $subcommand${NC}"
                echo ""
                court_help
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Analyze subcommands
handle_court_analyze_command() {
    local analyze_cmd="$1"
    shift
    
    case "$analyze_cmd" in
        judge)
            execute_court_cli "analyze judge" "$@"
            ;;
        help|--help|-h|"")
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","commands":["judge"],"usage":"./dev court analyze judge <name> [options]"}'
            else
                echo "Usage: ./dev court analyze <command>"
                echo ""
                echo "Available commands:"
                echo "  judge <name>     Analyze specific judge patterns and decisions"
                echo ""
                echo "Examples:"
                echo "  ./dev court analyze judge \"Rodney Gilstrap\" --court txed"
                echo "  ./dev court analyze judge \"Gilstrap\" --years 2020-2025"
            fi
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown analyze command: $analyze_cmd\"}"
            else
                echo -e "${RED}Unknown analyze command: $analyze_cmd${NC}"
                echo "Use: ./dev court analyze help"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Collect subcommands
handle_court_collect_command() {
    local collect_cmd="$1"
    shift
    
    case "$collect_cmd" in
        court)
            execute_court_cli "collect court" "$@"
            ;;
        judge)
            execute_court_cli "collect judge" "$@"
            ;;
        help|--help|-h|"")
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","commands":["court","judge"],"usage":"./dev court collect <command> [options]"}'
            else
                echo "Usage: ./dev court collect <command>"
                echo ""
                echo "Available commands:"
                echo "  court <id>       Collect documents from specific court"
                echo "  judge <name>     Collect documents by specific judge"
                echo ""
                echo "Examples:"
                echo "  ./dev court collect court txed --years 2020-2025 --limit 100"
                echo "  ./dev court collect judge \"Rodney Gilstrap\" --court txed"
            fi
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown collect command: $collect_cmd\"}"
            else
                echo -e "${RED}Unknown collect command: $collect_cmd${NC}"
                echo "Use: ./dev court collect help"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Data subcommands
handle_court_data_command() {
    local data_cmd="$1"
    shift

    case "$data_cmd" in
        status)
            execute_court_cli "data status" "$@"
            ;;
        fix)
            execute_court_cli "data fix" "$@"
            ;;
        list)
            execute_court_cli "data list" "$@"
            ;;
        export)
            execute_court_cli "data export" "$@"
            ;;
        xml-summary)
            execute_court_cli "data xml-summary" "$@"
            ;;
        xml-extract)
            execute_court_cli "data xml-extract" "$@"
            ;;
        help|--help|-h|"")
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","commands":["status","fix","list","export","xml-summary","xml-extract"],"usage":"./dev court data <command> [options]"}'
            else
                echo "Usage: ./dev court data <command>"
                echo ""
                echo "Available commands:"
                echo "  status           Check data quality and coverage"
                echo "  fix              Fix data quality issues"
                echo "  list             List documents with filters"
                echo "  export           Export documents with full content"
                echo "  xml-summary      Show XML parsing coverage and quality"
                echo "  xml-extract      Extract specific XML metadata fields"
                echo ""
                echo "Examples:"
                echo "  ./dev court data status"
                echo "  ./dev court data fix --judge-attribution --filter-court txed"
                echo "  ./dev court data list --type opinion --court txed"
                echo "  ./dev court data export --judge \"Gilstrap\" --full-content"
                echo "  ./dev court data xml-summary"
                echo "  ./dev court data xml-extract --field citations --court txed"
            fi
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown data command: $data_cmd\"}"
            else
                echo -e "${RED}Unknown data command: $data_cmd${NC}"
                echo "Use: ./dev court data help"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Search subcommands
handle_court_search_command() {
    local search_cmd="$1"
    shift

    case "$search_cmd" in
        opinions)
            execute_court_cli "search opinions" "$@"
            ;;
        enhanced)
            execute_court_cli "search enhanced" "$@"
            ;;
        help|--help|-h|"")
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","commands":["opinions","enhanced"],"usage":"./dev court search <command> [query] [options]"}'
            else
                echo "Usage: ./dev court search <command>"
                echo ""
                echo "Available commands:"
                echo "  opinions [query] Search through indexed opinions and documents"
                echo "  enhanced [query] Search with XML-enhanced filtering and metadata"
                echo ""
                echo "Examples:"
                echo "  ./dev court search opinions \"patent infringement\""
                echo "  ./dev court search opinions --judge Gilstrap --court txed"
                echo "  ./dev court search enhanced \"patent\" --xml-only --min-citations 5"
                echo "  ./dev court search enhanced --has-motions --court txed --show-xml"
            fi
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown search command: $search_cmd\"}"
            else
                echo -e "${RED}Unknown search command: $search_cmd${NC}"
                echo "Use: ./dev court search help"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Pipeline subcommands
handle_court_pipeline_command() {
    local pipeline_cmd="$1"
    shift
    
    case "$pipeline_cmd" in
        run)
            execute_court_cli "pipeline run" "$@"
            ;;
        help|--help|-h|"")
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","commands":["run"],"usage":"./dev court pipeline run [options]"}'
            else
                echo "Usage: ./dev court pipeline <command>"
                echo ""
                echo "Available commands:"
                echo "  run              Run the 11-stage enhancement pipeline"
                echo ""
                echo "Examples:"
                echo "  ./dev court pipeline run --limit 100 --unprocessed"
                echo "  ./dev court pipeline run --force --extract-pdfs"
            fi
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"error\",\"message\":\"Unknown pipeline command: $pipeline_cmd\"}"
            else
                echo -e "${RED}Unknown pipeline command: $pipeline_cmd${NC}"
                echo "Use: ./dev court pipeline help"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Court processor status
court_status() {
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        local status="stopped"
        local api_status="unavailable"
        local data_count=0
        
        # Check service status
        if $DOCKER_COMPOSE ps court-processor | grep -q "Up"; then
            status="running"
            
            # Check API health
            if curl -s "http://localhost:${COURT_PROCESSOR_PORT:-8104}/" >/dev/null 2>&1; then
                api_status="healthy"
            else
                api_status="unhealthy"
            fi
            
            # Get document count if service is running
            if [ "$api_status" = "healthy" ]; then
                data_count=$(curl -s "http://localhost:${COURT_PROCESSOR_PORT:-8104}/list?limit=1" | jq -r '.count // 0' 2>/dev/null || echo 0)
            fi
        fi
        
        echo "{\"status\":\"$status\",\"api\":\"$api_status\",\"port\":${COURT_PROCESSOR_PORT:-8104},\"documents\":$data_count}"
    else
        echo -e "\n${CYAN}📋 Court Processor Status${NC}\n"
        
        # Service status
        if $DOCKER_COMPOSE ps court-processor | grep -q "Up"; then
            echo -e "${GREEN}✅ Service: Running${NC}"
            
            # API health check
            if curl -s "http://localhost:${COURT_PROCESSOR_PORT:-8104}/" >/dev/null 2>&1; then
                echo -e "${GREEN}✅ API: Healthy (port ${COURT_PROCESSOR_PORT:-8104})${NC}"
                
                # Document count
                local count=$(curl -s "http://localhost:${COURT_PROCESSOR_PORT:-8104}/list?limit=1" | jq -r '.count // 0' 2>/dev/null || echo "unknown")
                echo -e "${CYAN}📄 Documents: ${count}${NC}"
                
                # Quick data quality check via CLI
                echo -e "\n${CYAN}Data Quality:${NC}"
                execute_court_cli "data status" | head -20
            else
                echo -e "${YELLOW}⚠️  API: Unhealthy (port ${COURT_PROCESSOR_PORT:-8104})${NC}"
            fi
        else
            echo -e "${RED}❌ Service: Not running${NC}"
            echo "Start with: ./dev up"
        fi
    fi
}

# Court processor API examples and access
court_api_examples() {
    local cmd="$1"

    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{"status":"info","api_port":"'${COURT_PROCESSOR_PORT:-8104}'","endpoints":["bulk","documents","search","list"]}'
    else
        echo -e "${CYAN}📡 Court Processor API Access${NC}"
        echo ""
        echo -e "${GREEN}API Base URL:${NC} http://localhost:${COURT_PROCESSOR_PORT:-8104}/"
        echo ""
        echo -e "${CYAN}🔍 Key Endpoints:${NC}"
        echo "  GET /                           # API documentation and health"
        echo "  GET /bulk/judge/{name}          # Bulk retrieval by judge with XML metadata"
        echo "  GET /documents/{id}             # Individual document with full metadata"
        echo "  GET /search?q={query}           # Search documents"
        echo "  GET /list                       # List recent documents"
        echo ""
        echo -e "${CYAN}💡 Bulk Data Examples:${NC}"
        echo "  # Get all 020lead documents for Gilstrap with XML metadata (metadata only)"
        echo "  curl \"http://localhost:${COURT_PROCESSOR_PORT:-8104}/bulk/judge/Gilstrap?type=020lead&include_text=false\""
        echo ""
        echo "  # Get all published opinions for Tigar with full text"
        echo "  curl \"http://localhost:${COURT_PROCESSOR_PORT:-8104}/bulk/judge/Tigar?type=published_opinion&include_text=true\""
        echo ""
        echo "  # Get all document types for a judge"
        echo "  curl \"http://localhost:${COURT_PROCESSOR_PORT:-8104}/bulk/judge/Gilstrap?type=all&include_text=false\""
        echo ""
        echo -e "${CYAN}📊 XML Metadata Features:${NC}"
        echo "  • parsing_enabled: Whether XML parsing was applied"
        echo "  • citation_count: Number of legal citations found"
        echo "  • citations[]: Array of extracted citations"
        echo "  • legal_motions[]: Array of legal motions identified"
        echo "  • federal_rules[]: Array of federal rules referenced"
        echo "  • statutes[]: Array of statutes referenced"
        echo "  • judge_full: Full judge name from XML parsing"
        echo ""
        echo -e "${CYAN}⚡ Quick Test:${NC}"
        echo "  curl -s \"http://localhost:${COURT_PROCESSOR_PORT:-8104}/\" | jq ."
    fi
}

# Court processor help
court_help() {
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{
            "status": "info",
            "description": "Court Processor CLI Integration",
            "commands": {
                "analyze": "Analyze judges, courts, and legal patterns",
                "collect": "Collect court documents from various sources", 
                "data": "Manage data quality and collection",
                "search": "Search indexed court documents",
                "pipeline": "Run document processing pipeline",
                "status": "Check court processor service status"
            },
            "examples": [
                "./dev court analyze judge \"Rodney Gilstrap\"",
                "./dev court collect court txed --years 2020-2025",
                "./dev court data status",
                "./dev court search opinions \"patent\""
            ]
        }'
    else
        echo "Usage: ./dev court <command> [options]"
        echo ""
        echo "Court Processor - Legal Document Analysis & Collection"
        echo ""
        echo "Available commands:"
        echo "  analyze          Analyze judges, courts, and legal patterns"
        echo "  collect          Collect court documents from various sources"
        echo "  data             Manage data quality and XML-enhanced collection"
        echo "  search           Search indexed court documents (basic & enhanced)"
        echo "  pipeline         Run document processing pipeline"
        echo "  api              Show API endpoints and bulk data examples"
        echo "  status           Check court processor service status"
        echo ""
        echo "XML-Enhanced Features:"
        echo "  ./dev court data xml-summary                    # Show XML parsing coverage"
        echo "  ./dev court data xml-extract --field citations  # Extract citation data"
        echo "  ./dev court search enhanced --xml-only           # Search XML documents only"
        echo ""
        echo "Examples:"
        echo "  ./dev court analyze judge \"Rodney Gilstrap\" --court txed"
        echo "  ./dev court collect court txed --years 2020-2025 --limit 100"
        echo "  ./dev court data status"
        echo "  ./dev court search opinions \"patent infringement\""
        echo "  ./dev court search enhanced --min-citations 5 --show-xml"
        echo "  ./dev court pipeline run --limit 50 --unprocessed"
        echo ""
        echo "For command-specific help:"
        echo "  ./dev court <command> help"
        echo ""
        echo "Note: Court processor service must be running (./dev up)"
    fi
}