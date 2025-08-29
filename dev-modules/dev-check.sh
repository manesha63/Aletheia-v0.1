#!/bin/bash

# ============================================================================
# Dev CLI Unified Check Module
# ============================================================================
# Consolidated checking and diagnostics commands
# Replaces: health, doctor, audit with unified interface

# Handle check command
handle_check_command() {
    local subcommand="$1"
    shift
    
    case "$subcommand" in
        --health|health)
            check_health "$@"
            ;;
        --docker|docker)
            check_docker "$@"
            ;;
        --env|env)
            check_env "$@"
            ;;
        --ports|ports)
            check_ports "$@"
            ;;
        --all|"")
            # Default comprehensive check
            check_comprehensive "$@"
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"error","message":"Unknown check subcommand: '$subcommand'"}'
            else
                echo -e "${RED}Unknown check subcommand: $subcommand${NC}"
                echo "Usage: ./dev check [--health|--docker|--env|--ports|--all]"
            fi
            return $EXIT_INVALID_ARGUMENT
            ;;
    esac
}

# Comprehensive check (default)
check_comprehensive() {
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Comprehensive System Check"
    fi
    
    local total_issues=0
    local total_warnings=0
    
    # 1. Docker Environment
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}1. Docker Environment:${NC}"
    fi
    
    check_docker_internal
    local docker_issues=$?
    total_issues=$((total_issues + docker_issues))
    
    # 2. Configuration
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}2. Configuration:${NC}"
    fi
    
    check_config_internal
    local config_issues=$?
    total_issues=$((total_issues + config_issues))
    
    # 3. Port Availability
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}3. Port Availability:${NC}"
    fi
    
    check_ports_internal
    local port_warnings=$?
    total_warnings=$((total_warnings + port_warnings))
    
    # 4. Service Health
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}4. Service Health:${NC}"
    fi
    
    check_health_internal
    local health_issues=$?
    total_warnings=$((total_warnings + health_issues))
    
    # Summary
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"issues\":$total_issues,\"warnings\":$total_warnings}"
    else
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if [ $total_issues -eq 0 ] && [ $total_warnings -eq 0 ]; then
            echo -e "${GREEN}✓ All checks passed${NC}"
        elif [ $total_issues -eq 0 ]; then
            echo -e "${YELLOW}⚠ Checks passed with $total_warnings warning(s)${NC}"
        else
            echo -e "${RED}✗ Check failed: $total_issues issue(s), $total_warnings warning(s)${NC}"
        fi
    fi
    
    [ $total_issues -eq 0 ] && return $EXIT_SUCCESS || return $EXIT_CONFIG_ERROR
}

# Health check (replaces utils_health)
check_health() {
    check_requirements || return $?
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Service Health Check"
    fi
    
    check_health_internal
    local issues=$?
    
    [ $issues -eq 0 ] && return $EXIT_SUCCESS || return $EXIT_CONFIG_ERROR
}

# Internal health check function (returns count of issues)
check_health_internal() {
    # Get all services using shared function
    local all_services=$(get_all_services)
    
    local healthy=0
    local unhealthy=0
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}Checking all services:${NC}"
    fi
    
    for service in $all_services; do
        # Get container name using shared function
        local container_name=$(get_container_name "$service")
        
        # Get service status using shared function
        local status=$(get_service_status "$service")
        
        if [[ "$status" == running:* ]]; then
            local health="${status#running:}"
            if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓${NC} $service is running"
                fi
                healthy=$((healthy + 1))
            else
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${YELLOW}⚠${NC} $service is $health"
                fi
                unhealthy=$((unhealthy + 1))
            fi
        else
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${RED}✗${NC} $service is $status"
            fi
            unhealthy=$((unhealthy + 1))
        fi
    done
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"healthy\":$healthy,\"unhealthy\":$unhealthy}"
    else
        echo ""
        echo -e "${CYAN}Summary:${NC}"
        if [ $unhealthy -eq 0 ]; then
            echo -e "${GREEN}✓ All services healthy${NC}"
        else
            echo -e "${YELLOW}⚠ $unhealthy service(s) not running${NC}"
        fi
    fi
    
    return $unhealthy
}

# Docker check (replaces utils_doctor docker parts)
check_docker() {
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Docker Environment Check"
    fi
    
    check_docker_internal
    local issues=$?
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"issues\":$issues}"
    else
        echo ""
        echo -e "${CYAN}Summary:${NC}"
        if [ $issues -eq 0 ]; then
            echo -e "${GREEN}✓ Docker environment healthy${NC}"
        else
            echo -e "${RED}✗ $issues Docker issue(s) found${NC}"
        fi
    fi
    
    [ $issues -eq 0 ] && return $EXIT_SUCCESS || return $EXIT_CONFIG_ERROR
}

# Internal docker check function (returns count of issues)
check_docker_internal() {
    local issues=0
    
    # Check Docker installed
    if ! command -v docker &> /dev/null; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} Docker not installed"
            echo -e "  ${YELLOW}→ Install from: https://www.docker.com/products/docker-desktop${NC}"
        fi
        issues=$((issues + 1))
    else
        local docker_version=$(docker --version | cut -d' ' -f3 | tr -d ',')
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Docker installed ($docker_version)"
        fi
        
        # Check Docker daemon
        if docker info &> /dev/null; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${GREEN}✓${NC} Docker daemon running"
                
                # Check Docker memory
                local mem_limit=$(docker info --format '{{.MemTotal}}' 2>/dev/null)
                if [ -n "$mem_limit" ]; then
                    echo -e "${GREEN}✓${NC} Docker memory: $mem_limit"
                fi
            fi
        else
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${RED}✗${NC} Docker daemon not running"
                echo -e "  ${YELLOW}→ Start Docker Desktop application${NC}"
            fi
            issues=$((issues + 1))
        fi
    fi
    
    # Check docker-compose
    if [ -z "$DOCKER_COMPOSE" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} docker-compose not installed"
        fi
        issues=$((issues + 1))
    else
        local compose_version=$($DOCKER_COMPOSE version --short 2>/dev/null || echo "unknown")
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} docker-compose installed ($compose_version)"
        fi
    fi
    
    return $issues
}

# Configuration check
check_config_internal() {
    local issues=0
    local warnings=0
    
    # Check .env file
    if [ ! -f .env ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} No .env file found"
            echo -e "  ${YELLOW}→ Run './dev setup' to create one${NC}"
        fi
        issues=$((issues + 1))
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} .env file exists"
        fi
        
        source .env
        
        # Check for CHANGE_ME placeholders
        if grep -q "CHANGE_ME" .env 2>/dev/null; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${RED}✗${NC} Found CHANGE_ME placeholders in .env"
                echo -e "  ${YELLOW}→ Update all CHANGE_ME values with secure passwords${NC}"
            fi
            issues=$((issues + 1))
        fi
        
        # Check for weak passwords
        if [[ "$DB_PASSWORD" =~ ^(password|123456|admin|default|aletheia123|postgres)$ ]]; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${YELLOW}⚠${NC} Weak DB_PASSWORD detected (security risk)"
            fi
            warnings=$((warnings + 1))
        fi
        
        # Check required variables
        local required_vars="DB_PASSWORD N8N_ENCRYPTION_KEY NEXTAUTH_SECRET"
        for var in $required_vars; do
            if ! grep -q "^$var=" .env 2>/dev/null; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${RED}✗${NC} Missing required: $var"
                fi
                issues=$((issues + 1))
            fi
        done
    fi
    
    # Check docker-compose.yml
    if [ -f "docker-compose.yml" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} docker-compose.yml exists"
        fi
        # Validate syntax
        if $DOCKER_COMPOSE config > /dev/null 2>&1; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${GREEN}✓${NC} docker-compose.yml syntax valid"
            fi
        else
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${RED}✗${NC} docker-compose.yml has syntax errors"
            fi
            issues=$((issues + 1))
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} docker-compose.yml missing"
        fi
        issues=$((issues + 1))
    fi
    
    return $issues
}

# Port check
check_ports() {
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Port Availability Check"
    fi
    
    check_ports_internal
    local warnings=$?
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"warnings\":$warnings}"
    else
        echo ""
        if [ $warnings -eq 0 ]; then
            echo -e "${GREEN}✓ All ports configured correctly${NC}"
        else
            echo -e "${YELLOW}⚠ $warnings port issue(s) found${NC}"
        fi
    fi
    
    return $EXIT_SUCCESS
}

# Internal port check function (returns count of warnings)
check_ports_internal() {
    local ports_to_check="${WEB_PORT:-8080} ${N8N_PORT:-8100} ${AI_PORTAL_PORT:-8102} ${COURT_PROCESSOR_PORT:-8104} ${POSTGRES_PORT:-8200} ${REDIS_PORT:-8201}"
    local port_issues=0
    
    for port in $ports_to_check; do
        if lsof -i :$port > /dev/null 2>&1; then
            local service_name=$(docker ps --format "table {{.Names}}\t{{.Ports}}" | grep $port | awk '{print $1}' | head -1)
            if [ -n "$service_name" ]; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓${NC} Port $port in use by $service_name (expected)"
                fi
            else
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${YELLOW}⚠${NC} Port $port in use by non-Docker process"
                fi
                port_issues=$((port_issues + 1))
            fi
        else
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${GREEN}✓${NC} Port $port available"
            fi
        fi
    done
    
    return $port_issues
}

# Environment variable check (replaces audit for env)
check_env() {
    # Just call the existing audit command for now
    # This maintains backward compatibility
    handle_audit_command env "$@"
}

# Export functions
export -f handle_check_command
export -f check_comprehensive
export -f check_health
export -f check_health_internal
export -f check_docker
export -f check_docker_internal
export -f check_config_internal
export -f check_ports
export -f check_ports_internal
export -f check_env