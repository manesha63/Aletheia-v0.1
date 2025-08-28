#!/bin/bash

# ============================================================================
# Dev CLI Environment Variable Audit Module  
# ============================================================================
# This module audits environment variables used in docker-compose files

# Handle audit commands
handle_audit_command() {
    local cmd="$1"
    shift
    
    case "$cmd" in
        env|environment)
            audit_env "$@"
            ;;
        ports)
            audit_ports "$@"
            ;;
        volumes)
            audit_volumes "$@"
            ;;
        ""|all)
            audit_all "$@"
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"error","message":"Unknown audit command"}'
            else
                echo -e "${RED}Unknown audit command: $cmd${NC}"
                echo "Usage: ./dev audit [env|ports|volumes|all]"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Audit environment variables
audit_env() {
    local fix=false
    local generate_docs=false
    
    for arg in "$@"; do
        case "$arg" in
            --fix)
                fix=true
                ;;
            --generate-docs)
                generate_docs=true
                ;;
        esac
    done
    
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Environment Variable Audit"
    fi
    
    # Extract all environment variables from docker-compose.yml
    local compose_vars=$(grep -oE '\$\{[A-Z_][A-Z0-9_]*(:?-[^}]*)?\}' docker-compose.yml 2>/dev/null | \
                         sed -E 's/\$\{([A-Z_][A-Z0-9_]*)(:?-[^}]*)?\}/\1/' | sort -u)
    
    # Get variables defined in .env
    local env_vars=""
    if [ -f .env ]; then
        env_vars=$(grep -E '^[A-Z_][A-Z0-9_]*=' .env | cut -d= -f1 | sort -u)
    fi
    
    # Get variables with defaults first
    local vars_with_defaults=""
    local defaults_list=$(grep -oE '\$\{[A-Z_][A-Z0-9_]*:-[^}]+\}' docker-compose.yml 2>/dev/null | \
                         sed -E 's/\$\{([A-Z_][A-Z0-9_]*):-[^}]+\}/\1/' | sort -u)
    
    # Find undefined variables
    local undefined=""
    local undefined_count=0
    local undefined_no_default=""
    local undefined_no_default_count=0
    local defined_count=0
    local unused=""
    local unused_count=0
    
    for var in $compose_vars; do
        if ! echo "$env_vars" | grep -q "^$var$"; then
            # Check if it has a default value
            if echo "$defaults_list" | grep -q "^$var$"; then
                # Has default, not really undefined
                undefined="$undefined $var"
            else
                # No default, truly undefined
                undefined="$undefined $var"
                undefined_no_default="$undefined_no_default $var"
                undefined_no_default_count=$((undefined_no_default_count + 1))
            fi
            undefined_count=$((undefined_count + 1))
        else
            defined_count=$((defined_count + 1))
        fi
    done
    
    # Find unused variables (defined but not used)
    for var in $env_vars; do
        if ! echo "$compose_vars" | grep -q "^$var$"; then
            unused="$unused $var"
            unused_count=$((unused_count + 1))
        fi
    done
    
    # Get variables with defaults
    local with_defaults=$(grep -oE '\$\{[A-Z_][A-Z0-9_]*:-[^}]+\}' docker-compose.yml 2>/dev/null | \
                         sed -E 's/\$\{([A-Z_][A-Z0-9_]*):-([^}]+)\}/\1:\2/' | sort -u)
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo -n '{"status":"success",'
        echo -n '"summary":{'
        echo -n '"total_used":'$(echo "$compose_vars" | wc -w)','
        echo -n '"defined":'$defined_count','
        echo -n '"undefined":'$undefined_count','
        echo -n '"unused":'$unused_count'},'
        
        echo -n '"undefined":['
        first=true
        for var in $undefined; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$var\""
        done
        echo -n '],'
        
        echo -n '"unused":['
        first=true
        for var in $unused; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$var\""
        done
        echo -n ']}'
    else
        # Display summary
        echo -e "${CYAN}Summary:${NC}"
        echo -e "  Variables in docker-compose: $(echo "$compose_vars" | wc -w)"
        echo -e "  Variables defined in .env:   ${GREEN}$defined_count${NC}"
        if [ $undefined_no_default_count -gt 0 ]; then
            echo -e "  Variables undefined (no default): ${RED}$undefined_no_default_count${NC}"
        fi
        local with_default_count=$((undefined_count - undefined_no_default_count))
        if [ $with_default_count -gt 0 ]; then
            echo -e "  Variables with defaults:     ${YELLOW}$with_default_count${NC}"
        fi
        echo -e "  Variables unused:            ${YELLOW}$unused_count${NC}"
        echo ""
        
        # Show undefined variables that need attention
        if [ $undefined_no_default_count -gt 0 ]; then
            echo -e "${RED}⚠ Undefined Variables (no defaults):${NC}"
            for var in $undefined_no_default; do
                echo -e "  ${RED}✗${NC} $var"
            done
            echo ""
        fi
        
        # Show variables with defaults
        local vars_with_defaults_to_show=""
        for var in $undefined; do
            if echo "$defaults_list" | grep -q "^$var$"; then
                vars_with_defaults_to_show="$vars_with_defaults_to_show $var"
            fi
        done
        
        if [ -n "$vars_with_defaults_to_show" ]; then
            echo -e "${YELLOW}ℹ Variables Using Defaults:${NC}"
            for var in $vars_with_defaults_to_show; do
                default=$(echo "$with_defaults" | grep "^$var:" | cut -d: -f2-)
                echo -e "  ${YELLOW}○${NC} $var (default: $default)"
            done
            echo ""
        fi
        
        # Show unused variables
        if [ $unused_count -gt 0 ]; then
            echo -e "${YELLOW}⚠ Unused Variables (defined but not referenced):${NC}"
            for var in $unused; do
                value=$(grep "^$var=" .env | cut -d= -f2)
                if [ ${#value} -gt 30 ]; then
                    value="${value:0:30}..."
                fi
                echo -e "  ${YELLOW}○${NC} $var = $value"
            done
            echo ""
        fi
        
        # Variable usage by service
        echo -e "${CYAN}Variable Usage by Service:${NC}"
        for service in $($DOCKER_COMPOSE config --services 2>/dev/null | head -5); do
            service_vars=$($DOCKER_COMPOSE config 2>/dev/null | \
                          awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                          grep -oE '\$\{[A-Z_][A-Z0-9_]*(:?-[^}]*)?\}' | \
                          sed -E 's/\$\{([A-Z_][A-Z0-9_]*)(:?-[^}]*)?\}/\1/' | sort -u)
            if [ -n "$service_vars" ]; then
                echo -e "  ${GREEN}$service:${NC} $(echo $service_vars | tr ' ' ', ')"
            fi
        done
        echo ""
        
        # Recommendations
        if [ $undefined_count -gt 0 ] && [ "$fix" = true ]; then
            echo -e "${CYAN}Generating missing variables...${NC}"
            for var in $undefined; do
                default=$(echo "$with_defaults" | grep "^$var:" | cut -d: -f2-)
                if [ -z "$default" ]; then
                    echo "$var=" >> .env
                    echo -e "  ${GREEN}✓${NC} Added $var to .env (empty)"
                else
                    echo "$var=$default" >> .env
                    echo -e "  ${GREEN}✓${NC} Added $var=$default to .env"
                fi
            done
        elif [ $undefined_count -gt 0 ]; then
            echo -e "${CYAN}Recommendations:${NC}"
            echo -e "  • Run ${GREEN}./dev audit env --fix${NC} to add missing variables to .env"
        fi
        
        if [ $unused_count -gt 0 ]; then
            echo -e "  • Review unused variables and remove if not needed"
        fi
    fi
}

# Audit port configurations
audit_ports() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Port Configuration Audit"
    fi
    
    # Extract port mappings from docker-compose
    local port_mappings=$($DOCKER_COMPOSE config 2>/dev/null | \
                         grep -E '^\s+- "[0-9]+:[0-9]+"|\s+- [0-9]+:[0-9]+' | \
                         sed -E 's/.*"?([0-9]+):([0-9]+)"?.*/\1:\2/' | sort -u)
    
    # Check which ports are in use
    echo -e "${CYAN}Port Mappings:${NC}"
    for mapping in $port_mappings; do
        host_port=$(echo $mapping | cut -d: -f1)
        container_port=$(echo $mapping | cut -d: -f2)
        
        # Check if port is in use
        if lsof -Pi :$host_port -sTCP:LISTEN -t >/dev/null 2>&1; then
            service_using=$(docker ps --format "table {{.Names}}\t{{.Ports}}" | grep ":$host_port->" | awk '{print $1}')
            echo -e "  ${GREEN}✓${NC} :$host_port -> :$container_port (used by $service_using)"
        else
            echo -e "  ${YELLOW}○${NC} :$host_port -> :$container_port (not in use)"
        fi
    done
    
    # Check for port conflicts
    echo ""
    echo -e "${CYAN}Checking for conflicts:${NC}"
    local conflicts=0
    for port in $(echo "$port_mappings" | cut -d: -f1 | sort | uniq -d); do
        echo -e "  ${RED}✗${NC} Port $port is mapped multiple times!"
        conflicts=$((conflicts + 1))
    done
    
    if [ $conflicts -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} No port conflicts detected"
    fi
}

# Audit volumes
audit_volumes() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Volume Configuration Audit"
    fi
    
    # Get defined volumes
    local defined_volumes=$($DOCKER_COMPOSE config 2>/dev/null | \
                           awk '/^volumes:$/,/^[a-z]+:$/' | \
                           grep -E '^  [a-z_]+:$' | \
                           sed 's/://g' | tr -d ' ' | sort)
    
    # Get actual Docker volumes for this project
    local actual_volumes=$(docker volume ls --format "{{.Name}}" | \
                          grep "^${PROJECT_NAME}_" | \
                          sed "s/^${PROJECT_NAME}_//" | sort)
    
    echo -e "${CYAN}Defined Volumes:${NC}"
    for vol in $defined_volumes; do
        actual_name="${PROJECT_NAME}_${vol}"
        if docker volume ls --format "{{.Name}}" | grep -q "^$actual_name$"; then
            size=$(docker volume inspect $actual_name --format '{{.Mountpoint}}' 2>/dev/null | xargs du -sh 2>/dev/null | cut -f1)
            echo -e "  ${GREEN}✓${NC} $vol (exists, size: ${size:-unknown})"
        else
            echo -e "  ${YELLOW}○${NC} $vol (not created)"
        fi
    done
    
    # Check for orphaned volumes
    echo ""
    echo -e "${CYAN}Orphaned Volumes:${NC}"
    local orphans=0
    for vol in $actual_volumes; do
        if ! echo "$defined_volumes" | grep -q "^$vol$"; then
            actual_name="${PROJECT_NAME}_${vol}"
            size=$(docker volume inspect $actual_name --format '{{.Mountpoint}}' 2>/dev/null | xargs du -sh 2>/dev/null | cut -f1)
            echo -e "  ${RED}✗${NC} $vol (size: ${size:-unknown})"
            orphans=$((orphans + 1))
        fi
    done
    
    if [ $orphans -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} No orphaned volumes"
    fi
}

# Audit everything
audit_all() {
    audit_env "$@"
    echo ""
    audit_ports "$@"
    echo ""
    audit_volumes "$@"
}

# Export functions
export -f handle_audit_command
export -f audit_env
export -f audit_ports  
export -f audit_volumes
export -f audit_all