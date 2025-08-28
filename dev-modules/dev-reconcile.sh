#!/bin/bash

# ============================================================================
# Dev CLI Service Reconciliation Module
# ============================================================================
# This module handles service discovery and reconciliation between
# docker-compose definitions and actual running containers

# Handle reconcile commands
handle_reconcile_command() {
    local cmd="$1"
    shift
    
    case "$cmd" in
        ""|status)
            reconcile_status "$@"
            ;;
        clean|cleanup)
            reconcile_cleanup "$@"
            ;;
        fix)
            reconcile_fix "$@"
            ;;
        *)
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"error","message":"Unknown reconcile command"}'
            else
                echo -e "${RED}Unknown reconcile command: $cmd${NC}"
                echo "Usage: ./dev reconcile [status|clean|fix]"
            fi
            return $EXIT_CONFIG_ERROR
            ;;
    esac
}

# Show reconciliation status
reconcile_status() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Service Reconciliation Report"
    fi
    
    # Get services from docker-compose
    local compose_services
    compose_services=$($DOCKER_COMPOSE config --services 2>/dev/null | sort)
    local compose_count=$(echo "$compose_services" | wc -l)
    
    # Get all containers for this project
    local all_containers
    all_containers=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT_NAME}" --format "{{.Names}}" | sort)
    local container_count=$(echo "$all_containers" | grep -c .)
    
    # Get running containers
    local running_containers
    running_containers=$(docker ps --filter "label=com.docker.compose.project=${PROJECT_NAME}" --format "{{.Names}}" | sort)
    local running_count=$(echo "$running_containers" | grep -c . || echo "0")
    
    # Find orphaned containers (containers not matching any service)
    local orphans=""
    local orphan_count=0
    
    for container in $all_containers; do
        local found=false
        for service in $compose_services; do
            # Check if container name contains the service name
            if [[ "$container" == *"$service"* ]] || [[ "$container" == "$service" ]]; then
                found=true
                break
            fi
        done
        if [ "$found" = false ]; then
            orphans="$orphans $container"
            orphan_count=$((orphan_count + 1))
        fi
    done
    
    # Find services without containers
    local missing=""
    local missing_count=0
    
    for service in $compose_services; do
        local found=false
        for container in $all_containers; do
            if [[ "$container" == *"$service"* ]] || [[ "$container" == "$service" ]]; then
                found=true
                break
            fi
        done
        if [ "$found" = false ]; then
            missing="$missing $service"
            missing_count=$((missing_count + 1))
        fi
    done
    
    # Find stopped containers
    local stopped=""
    local stopped_count=0
    
    for container in $all_containers; do
        local is_running=false
        for running in $running_containers; do
            if [ "$container" = "$running" ]; then
                is_running=true
                break
            fi
        done
        if [ "$is_running" = false ]; then
            stopped="$stopped $container"
            stopped_count=$((stopped_count + 1))
        fi
    done
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        # Build JSON output
        echo -n '{"status":"success",'
        echo -n '"summary":{'
        echo -n '"compose_services":'$compose_count','
        echo -n '"total_containers":'$container_count','
        echo -n '"running_containers":'$running_count','
        echo -n '"stopped_containers":'$stopped_count','
        echo -n '"orphaned_containers":'$orphan_count','
        echo -n '"missing_containers":'$missing_count'},'
        
        # Add arrays
        echo -n '"orphaned":['
        first=true
        for orphan in $orphans; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$orphan\""
        done
        echo -n '],'
        
        echo -n '"missing":['
        first=true
        for miss in $missing; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$miss\""
        done
        echo -n '],'
        
        echo -n '"stopped":['
        first=true
        for stop in $stopped; do
            if [ "$first" = true ]; then first=false; else echo -n ','; fi
            echo -n "\"$stop\""
        done
        echo -n ']}'
    else
        # Display summary
        echo -e "${CYAN}Summary:${NC}"
        echo -e "  Services defined:    $compose_count"
        echo -e "  Containers total:    $container_count"
        echo -e "  Containers running:  ${GREEN}$running_count${NC}"
        echo -e "  Containers stopped:  ${YELLOW}$stopped_count${NC}"
        echo ""
        
        # Display issues
        if [ $orphan_count -gt 0 ]; then
            echo -e "${YELLOW}⚠ Orphaned Containers (not in docker-compose.yml):${NC}"
            for orphan in $orphans; do
                local status=$(docker inspect --format='{{.State.Status}}' "$orphan" 2>/dev/null)
                echo -e "  ${RED}✗${NC} $orphan ($status)"
            done
            echo ""
        fi
        
        if [ $missing_count -gt 0 ]; then
            echo -e "${YELLOW}⚠ Missing Containers (defined but not created):${NC}"
            for miss in $missing; do
                echo -e "  ${YELLOW}○${NC} $miss"
            done
            echo ""
        fi
        
        if [ $stopped_count -gt 0 ]; then
            echo -e "${CYAN}Stopped Containers:${NC}"
            for stop in $stopped; do
                # Get exit code if available
                local exit_code=$(docker inspect --format='{{.State.ExitCode}}' "$stop" 2>/dev/null)
                if [ -n "$exit_code" ] && [ "$exit_code" != "0" ]; then
                    echo -e "  ${YELLOW}○${NC} $stop (exit code: $exit_code)"
                else
                    echo -e "  ${YELLOW}○${NC} $stop"
                fi
            done
            echo ""
        fi
        
        # Recommendations
        if [ $orphan_count -gt 0 ] || [ $missing_count -gt 0 ]; then
            echo -e "${CYAN}Recommendations:${NC}"
            if [ $orphan_count -gt 0 ]; then
                echo -e "  • Run ${GREEN}./dev reconcile clean${NC} to remove orphaned containers"
            fi
            if [ $missing_count -gt 0 ]; then
                echo -e "  • Run ${GREEN}./dev reconcile fix${NC} to create missing containers"
            fi
        else
            echo -e "${GREEN}✓ All services and containers are in sync${NC}"
        fi
    fi
}

# Clean up orphaned containers
reconcile_cleanup() {
    local force=false
    if [ "$1" = "--force" ] || [ "$1" = "-f" ]; then
        force=true
    fi
    
    check_requirements
    
    # Find orphans
    local compose_services=$($DOCKER_COMPOSE config --services 2>/dev/null)
    local all_containers=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT_NAME}" --format "{{.Names}}")
    local orphans=""
    
    for container in $all_containers; do
        local found=false
        for service in $compose_services; do
            if [[ "$container" == *"$service"* ]] || [[ "$container" == "$service" ]]; then
                found=true
                break
            fi
        done
        if [ "$found" = false ]; then
            orphans="$orphans $container"
        fi
    done
    
    if [ -z "$orphans" ]; then
        output_result "success" "No orphaned containers found"
        return $EXIT_SUCCESS
    fi
    
    echo -e "${YELLOW}Found orphaned containers:${NC}"
    for orphan in $orphans; do
        local status=$(docker inspect --format='{{.State.Status}}' "$orphan" 2>/dev/null)
        echo -e "  • $orphan ($status)"
    done
    echo ""
    
    if [ "$force" != true ]; then
        if ! confirm_operation "Remove these orphaned containers?" "N"; then
            output_result "info" "Cleanup cancelled"
            return $EXIT_USER_CANCELLED
        fi
    fi
    
    # Remove orphans
    for orphan in $orphans; do
        echo -e "${BLUE}Removing $orphan...${NC}"
        docker rm -f "$orphan" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Removed $orphan${NC}"
        else
            echo -e "${RED}✗ Failed to remove $orphan${NC}"
        fi
    done
    
    output_result "success" "Cleanup complete"
}

# Fix missing containers
reconcile_fix() {
    check_requirements
    
    # Find missing services
    local compose_services=$($DOCKER_COMPOSE config --services 2>/dev/null)
    local all_containers=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT_NAME}" --format "{{.Names}}")
    local missing=""
    
    for service in $compose_services; do
        local found=false
        for container in $all_containers; do
            if [[ "$container" == *"$service"* ]] || [[ "$container" == "$service" ]]; then
                found=true
                break
            fi
        done
        if [ "$found" = false ]; then
            missing="$missing $service"
        fi
    done
    
    if [ -z "$missing" ]; then
        output_result "success" "All service containers exist"
        return $EXIT_SUCCESS
    fi
    
    echo -e "${YELLOW}Missing containers for services:${NC}"
    for miss in $missing; do
        echo -e "  • $miss"
    done
    echo ""
    
    if ! confirm_operation "Create these missing containers?" "Y"; then
        output_result "info" "Fix cancelled"
        return $EXIT_USER_CANCELLED
    fi
    
    # Create missing containers
    for service in $missing; do
        echo -e "${BLUE}Creating container for $service...${NC}"
        $DOCKER_COMPOSE create "$service" 2>&1 | tail -3
        if [ ${PIPESTATUS[0]} -eq 0 ]; then
            echo -e "${GREEN}✓ Created container for $service${NC}"
        else
            echo -e "${RED}✗ Failed to create container for $service${NC}"
        fi
    done
    
    output_result "success" "Fix complete"
}

# Export functions
export -f handle_reconcile_command
export -f reconcile_status
export -f reconcile_cleanup
export -f reconcile_fix