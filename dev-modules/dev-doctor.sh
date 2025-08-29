#!/bin/bash

# ============================================================================
# Dev CLI Doctor Module
# ============================================================================
# This module handles system diagnostics and health checks

# Handle doctor command
handle_doctor_command() {
    utils_doctor "$@"
}

# System diagnostics
utils_doctor() {
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Comprehensive System Diagnostics"
    fi
    
    issues=0
    warnings=0
    
    # 1. Check Docker
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}1. Docker Environment:${NC}"
    fi
    
    if ! command -v docker &> /dev/null; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"docker_installed":false}'
        else
            echo -e "${RED}✗${NC} Docker not installed"
            echo -e "  ${YELLOW}→ Install from: https://www.docker.com/products/docker-desktop${NC}"
        fi
        issues=$((issues + 1))
    else
        local docker_version=$(docker --version | cut -d' ' -f3 | tr -d ',')
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo "{\"docker_installed\":true,\"docker_version\":\"$docker_version\"}"
        else
            echo -e "${GREEN}✓${NC} Docker installed ($docker_version)"
        fi
        
        # Check if Docker daemon is running
        if docker info &> /dev/null; then
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"docker_daemon_running":true}'
            else
                echo -e "${GREEN}✓${NC} Docker daemon running"
                
                # Check Docker memory
                local mem_limit=$(docker info --format '{{.MemTotal}}' 2>/dev/null)
                if [ -n "$mem_limit" ]; then
                    echo -e "${GREEN}✓${NC} Docker memory: $mem_limit"
                fi
            fi
        else
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"docker_daemon_running":false}'
            else
                echo -e "${RED}✗${NC} Docker daemon not running"
                echo -e "  ${YELLOW}→ Start Docker Desktop application${NC}"
            fi
            issues=$((issues + 1))
        fi
    fi
    
    # 2. Check docker-compose
    if [ -z "$DOCKER_COMPOSE" ]; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"docker_compose_installed":false}'
        else
            echo -e "${RED}✗${NC} $DOCKER_COMPOSE not installed"
        fi
        issues=$((issues + 1))
    else
        local compose_version=$($DOCKER_COMPOSE version --short 2>/dev/null || echo "unknown")
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo "{\"docker_compose_installed\":true,\"compose_version\":\"$compose_version\"}"
        else
            echo -e "${GREEN}✓${NC} $DOCKER_COMPOSE installed ($compose_version)"
        fi
    fi
    
    echo ""
    
    # 2. Check configuration
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}2. Configuration:${NC}"
    fi
    
    if [ ! -f .env ]; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"env_file_exists":false}'
        else
            echo -e "${RED}✗${NC} No .env file found"
            echo -e "  ${YELLOW}→ Run './dev setup' to create one${NC}"
        fi
        issues=$((issues + 1))
    else
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"env_file_exists":true}'
        else
            echo -e "${GREEN}✓${NC} .env file exists"
        fi
        
        # Check for CHANGE_ME placeholders
        if grep -q "CHANGE_ME" .env 2>/dev/null; then
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"env_has_placeholders":true}'
            else
                echo -e "${RED}✗${NC} Found CHANGE_ME placeholders in .env"
                echo -e "  ${YELLOW}→ Update all CHANGE_ME values with secure passwords${NC}"
            fi
            issues=$((issues + 1))
        fi
        
        # Check for weak passwords
        if grep -q "DB_PASSWORD=password\|DB_PASSWORD=123456\|DB_PASSWORD=admin" .env 2>/dev/null; then
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"weak_password":true}'
            else
                echo -e "${YELLOW}⚠${NC} Weak default password detected"
                echo -e "  ${YELLOW}→ Update DB_PASSWORD with a secure password${NC}"
            fi
            warnings=$((warnings + 1))
        fi
        
        # Check required variables
        local required_vars="DB_PASSWORD N8N_ENCRYPTION_KEY NEXTAUTH_SECRET"
        local missing_vars=""
        for var in $required_vars; do
            if ! grep -q "^$var=" .env 2>/dev/null; then
                missing_vars="$missing_vars $var"
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${RED}✗${NC} Missing required: $var"
                fi
                issues=$((issues + 1))
            fi
        done
        
        if [ -z "$missing_vars" ] && [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} All required variables set"
        fi
    fi
    
    echo ""
    
    # Summary
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"issues\":$issues,\"warnings\":$warnings}"
    else
        echo -e "${CYAN}Summary:${NC}"
        if [ $issues -eq 0 ] && [ $warnings -eq 0 ]; then
            echo -e "${GREEN}✓ System is healthy${NC}"
        elif [ $issues -eq 0 ]; then
            echo -e "${YELLOW}⚠ $warnings warning(s) found${NC}"
        else
            echo -e "${RED}✗ $issues issue(s) and $warnings warning(s) found${NC}"
        fi
    fi
    
    return $([ $issues -eq 0 ] && echo $EXIT_SUCCESS || echo $EXIT_CONFIG_ERROR)
}

# System health check
utils_health() {
    check_requirements || return $?
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Service Health Check"
    fi
    
    # Get all services using shared function
    local all_services=$(get_all_services)
    
    # Get running containers
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
}

# Export functions
export -f handle_doctor_command
export -f utils_doctor
export -f utils_health