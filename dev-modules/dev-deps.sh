#!/bin/bash

# ============================================================================
# Dev CLI Dependency Management Module
# ============================================================================
# This module analyzes and visualizes service dependencies

# Handle deps commands
handle_deps_command() {
    local service="$1"
    shift
    
    # Check for flags before service name
    local tree=false
    local check=false
    local order=false
    
    for arg in "$@" "$service"; do
        case "$arg" in
            --tree)
                tree=true
                ;;
            --check)
                check=true
                ;;
            --order)
                order=true
                ;;
            --*)
                # Skip other flags
                ;;
            *)
                # This might be the service name
                if [ "$arg" != "$service" ]; then
                    service="$arg"
                fi
                ;;
        esac
    done
    
    if [ "$order" = true ]; then
        show_startup_order
    elif [ "$check" = true ]; then
        check_dependencies "$service"
    elif [ -n "$service" ] && [ "$service" != "--"* ]; then
        show_service_deps "$service" "$tree"
    else
        show_all_deps "$tree"
    fi
}

# Show dependencies for all services
show_all_deps() {
    local tree="$1"
    
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Service Dependency Map"
    fi
    
    # Get all services and their dependencies
    local services=$($DOCKER_COMPOSE config --services 2>/dev/null | sort)
    
    # Use temp files for dependency maps (macOS bash doesn't support associative arrays)
    local deps_file="/tmp/deps_map_$$"
    local rdeps_file="/tmp/rdeps_map_$$"
    
    # Clean up temp files on exit
    trap "rm -f $deps_file $rdeps_file" EXIT
    
    # Build dependency map
    for service in $services; do
        # Handle both array format (- db) and extended format (db: condition:)
        local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                    awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                    awk '/depends_on:/,/^    [a-z]/' | \
                    grep -E "^    - |^      [a-z-]+:" | \
                    sed 's/^    - //;s/^      //;s/:.*$//' | \
                    grep -v "depends_on" | \
                    grep -v "condition" | \
                    tr '\n' ' ')
        
        echo "$service|$deps" >> "$deps_file"
        
        # Build reverse dependencies
        for dep in $deps; do
            echo "$dep|$service" >> "$rdeps_file"
        done
    done
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo -n '{"dependencies":{'
        first=true
        for service in $services; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$service\":["
            deps_first=true
            local deps=$(grep "^$service|" "$deps_file" | cut -d'|' -f2)
            for dep in $deps; do
                if [ "$deps_first" = true ]; then deps_first=false; else echo -n ','; fi
                echo -n "\"$dep\""
            done
            echo -n ']'
        done
        echo '}}'
    else
        # Display dependency information
        echo -e "${CYAN}Direct Dependencies:${NC}"
        for service in $services; do
            local deps=$(grep "^$service|" "$deps_file" 2>/dev/null | cut -d'|' -f2)
            if [ -n "$deps" ]; then
                echo -e "  ${GREEN}$service${NC} → $(echo $deps | tr ' ' ', ')"
            else
                echo -e "  ${YELLOW}$service${NC} → (no dependencies)"
            fi
        done
        
        echo ""
        echo -e "${CYAN}Services depended upon:${NC}"
        for service in $services; do
            local rdeps=$(grep "^$service|" "$rdeps_file" 2>/dev/null | cut -d'|' -f2 | tr '\n' ' ')
            if [ -n "$rdeps" ]; then
                echo -e "  ${GREEN}$service${NC} ← $(echo $rdeps | tr ' ' ', ')"
            fi
        done
        
        # Check for circular dependencies
        echo ""
        check_circular_deps
        
        # Show levels (startup order)
        echo ""
        show_dependency_levels
    fi
}

# Show dependencies for a specific service
show_service_deps() {
    local service="$1"
    local tree="$2"
    
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Dependencies for $service"
    fi
    
    # Check if service exists
    if ! $DOCKER_COMPOSE config --services 2>/dev/null | grep -q "^$service$"; then
        output_result "error" "Service '$service' not found"
        return $EXIT_CONFIG_ERROR
    fi
    
    # Get direct dependencies
    local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                grep -A20 "depends_on:" | \
                grep "^    - \|^      [a-z]" | \
                sed 's/^[- ]*//;s/:$//' | \
                grep -v "depends_on" | \
                grep -v "condition:")
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo -n "{\"service\":\"$service\",\"dependencies\":["
        first=true
        for dep in $deps; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$dep\""
        done
        echo ']}'
    else
        if [ -z "$deps" ]; then
            echo -e "${YELLOW}$service has no dependencies${NC}"
        else
            echo -e "${CYAN}Direct dependencies:${NC}"
            for dep in $deps; do
                local status="not created"
                if docker ps -a --format "{{.Names}}" | grep -q "$dep"; then
                    if docker ps --format "{{.Names}}" | grep -q "$dep"; then
                        status="${GREEN}running${NC}"
                    else
                        status="${YELLOW}stopped${NC}"
                    fi
                else
                    status="${RED}not created${NC}"
                fi
                echo -e "  → ${GREEN}$dep${NC} ($status)"
            done
        fi
        
        # Show what depends on this service
        echo ""
        echo -e "${CYAN}Services that depend on $service:${NC}"
        local found=false
        for other in $($DOCKER_COMPOSE config --services 2>/dev/null); do
            if [ "$other" != "$service" ]; then
                local other_deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                                  awk "/^  $other:$/,/^  [a-z-]+:$/" | \
                                  grep -A20 "depends_on:" | \
                                  grep "^    - \|^      [a-z]" | \
                                  sed 's/^[- ]*//;s/:$//' | \
                                  grep -v "depends_on" | \
                                  grep -v "condition:")
                
                if echo "$other_deps" | grep -q "^$service$"; then
                    echo -e "  ← ${GREEN}$other${NC}"
                    found=true
                fi
            fi
        done
        
        if [ "$found" = false ]; then
            echo -e "  ${YELLOW}(none)${NC}"
        fi
        
        # Show dependency tree if requested
        if [ "$tree" = true ]; then
            echo ""
            echo -e "${CYAN}Dependency tree:${NC}"
            show_dep_tree "$service" 0
        fi
    fi
}

# Recursive function to show dependency tree
show_dep_tree() {
    local service="$1"
    local level="$2"
    local visited="$3"
    
    # Prevent infinite loops
    if echo "$visited" | grep -q ":$service:"; then
        echo "$(printf '%*s' $((level*2)) '')├─ ${RED}$service (circular!)${NC}"
        return
    fi
    visited="$visited:$service:"
    
    # Print current service
    if [ $level -eq 0 ]; then
        echo -e "${GREEN}$service${NC}"
    else
        echo -e "$(printf '%*s' $((level*2)) '')├─ ${GREEN}$service${NC}"
    fi
    
    # Get dependencies
    local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                grep -A20 "depends_on:" | \
                grep "^    - \|^      [a-z]" | \
                sed 's/^[- ]*//;s/:$//' | \
                grep -v "depends_on" | \
                grep -v "condition:")
    
    # Recursively show dependencies
    for dep in $deps; do
        show_dep_tree "$dep" $((level+1)) "$visited"
    done
}

# Check for circular dependencies
check_circular_deps() {
    local services=$($DOCKER_COMPOSE config --services 2>/dev/null)
    local circular_found=false
    
    echo -e "${CYAN}Checking for circular dependencies:${NC}"
    
    for service in $services; do
        if has_circular_dep "$service" "$service" "$service"; then
            circular_found=true
        fi
    done
    
    if [ "$circular_found" = false ]; then
        echo -e "  ${GREEN}✓${NC} No circular dependencies detected"
    fi
}

# Helper to detect circular dependencies
has_circular_dep() {
    local start="$1"
    local current="$2"
    local visited="$3"
    
    local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                awk "/^  $current:$/,/^  [a-z-]+:$/" | \
                grep -A20 "depends_on:" | \
                grep "^    - \|^      [a-z]" | \
                sed 's/^[- ]*//;s/:$//' | \
                grep -v "depends_on" | \
                grep -v "condition:")
    
    for dep in $deps; do
        if [ "$dep" = "$start" ] && [ "$current" != "$start" ]; then
            echo -e "  ${RED}✗${NC} Circular: $start → ... → $current → $dep"
            return 0
        fi
        
        if ! echo "$visited" | grep -q ":$dep:"; then
            if has_circular_dep "$start" "$dep" "$visited:$dep:"; then
                return 0
            fi
        fi
    done
    
    return 1
}

# Show dependency levels (startup order)
show_dependency_levels() {
    echo -e "${CYAN}Recommended startup order:${NC}"
    
    local services=$($DOCKER_COMPOSE config --services 2>/dev/null)
    local deps_file="/tmp/deps_levels_$$"
    
    # Clean up temp file on exit
    trap "rm -f $deps_file" EXIT
    
    # Build dependency map
    for service in $services; do
        # Handle both array format (- db) and extended format (db: condition:)
        local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                    awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                    awk '/depends_on:/,/^    [a-z]/' | \
                    grep -E "^    - |^      [a-z-]+:" | \
                    sed 's/^    - //;s/^      //;s/:.*$//' | \
                    grep -v "depends_on" | \
                    grep -v "condition" | \
                    tr '\n' ' ')
        echo "$service|$deps" >> "$deps_file"
    done
    
    # Find services by level
    local level=0
    local remaining="$services"
    local started=""
    
    while [ -n "$remaining" ]; do
        local level_services=""
        
        for service in $remaining; do
            local can_start=true
            
            # Check if all dependencies have been started
            local deps=$(grep "^$service|" "$deps_file" 2>/dev/null | cut -d'|' -f2)
            for dep in $deps; do
                if ! echo "$started" | grep -q "\b$dep\b"; then
                    can_start=false
                    break
                fi
            done
            
            if [ "$can_start" = true ]; then
                level_services="$level_services $service"
            fi
        done
        
        if [ -z "$level_services" ]; then
            # Circular dependency or error
            if [ -n "$remaining" ]; then
                echo -e "  ${RED}Level $((level+1)):${NC} Cannot start: $remaining (circular or missing deps)"
            fi
            break
        fi
        
        level=$((level+1))
        echo -e "  ${GREEN}Level $level:${NC}$(echo $level_services | tr ' ' ', ')"
        
        # Update remaining and started lists
        started="$started $level_services"
        new_remaining=""
        for service in $remaining; do
            if ! echo "$level_services" | grep -q "\b$service\b"; then
                new_remaining="$new_remaining $service"
            fi
        done
        remaining="$new_remaining"
    done
}

# Show optimal startup order
show_startup_order() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Optimal Service Startup Order"
    fi
    
    show_dependency_levels
    
    echo ""
    echo -e "${CYAN}Start command:${NC}"
    echo -e "  ${GREEN}./dev up${NC} (starts in dependency order automatically)"
}

# Check if dependencies are healthy before starting a service
check_dependencies() {
    local service="$1"
    
    check_requirements
    
    if [ -z "$service" ]; then
        output_result "error" "Please specify a service to check"
        return $EXIT_CONFIG_ERROR
    fi
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}Checking dependencies for $service...${NC}"
    fi
    
    local deps=$($DOCKER_COMPOSE config 2>/dev/null | \
                awk "/^  $service:$/,/^  [a-z-]+:$/" | \
                grep -A20 "depends_on:" | \
                grep "^    - \|^      [a-z]" | \
                sed 's/^[- ]*//;s/:$//' | \
                grep -v "depends_on" | \
                grep -v "condition:")
    
    local all_ready=true
    local not_ready=""
    
    for dep in $deps; do
        # Check if container exists and is running
        if docker ps --format "{{.Names}}" | grep -q "$dep"; then
            # Check health if available
            local health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$dep" 2>/dev/null)
            
            if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
                echo -e "  ${GREEN}✓${NC} $dep is ready"
            else
                echo -e "  ${YELLOW}⚠${NC} $dep is $health"
                all_ready=false
                not_ready="$not_ready $dep"
            fi
        else
            echo -e "  ${RED}✗${NC} $dep is not running"
            all_ready=false
            not_ready="$not_ready $dep"
        fi
    done
    
    echo ""
    if [ "$all_ready" = true ]; then
        output_result "success" "All dependencies are ready for $service"
        return $EXIT_SUCCESS
    else
        output_result "error" "Dependencies not ready: $not_ready"
        echo -e "${CYAN}Start them with:${NC} ./dev up$not_ready"
        return $EXIT_SERVICE_UNAVAILABLE
    fi
}

# Export functions
export -f handle_deps_command
export -f show_all_deps
export -f show_service_deps
export -f show_dep_tree
export -f check_circular_deps
export -f has_circular_dep
export -f show_dependency_levels
export -f show_startup_order
export -f check_dependencies