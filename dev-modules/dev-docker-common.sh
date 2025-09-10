#!/bin/bash

# ============================================================================
# Dev CLI Docker Common Module
# ============================================================================
# Shared Docker operations to reduce redundancy and improve performance
# This module provides cached, efficient Docker operations used across all modules

# Cache variables (session-level)
SERVICES_CACHE=""
SERVICES_CACHE_TIME=0
CACHE_DURATION=60  # Cache for 60 seconds

# Container name mapping cache
declare -A CONTAINER_NAME_CACHE 2>/dev/null || CONTAINER_NAME_CACHE=""

# ============================================================================
# Core Docker Operations
# ============================================================================

# Get container name for a service (with caching)
get_container_name() {
    local service="$1"
    
    # Try bash associative array if available (bash 4+)
    if [ -n "$CONTAINER_NAME_CACHE" ] && declare -p CONTAINER_NAME_CACHE &>/dev/null; then
        if [ -n "${CONTAINER_NAME_CACHE[$service]}" ]; then
            echo "${CONTAINER_NAME_CACHE[$service]}"
            return
        fi
    fi
    
    # Get container name from docker-compose config
    local container_name=$($DOCKER_COMPOSE config 2>/dev/null | \
        grep -A 10 "^  $service:" | \
        grep "container_name:" | \
        awk '{print $2}')
    
    # Use default naming if not specified
    if [ -z "$container_name" ]; then
        container_name="${PROJECT_NAME}-${service}-1"
    fi
    
    # Cache if possible
    if [ -n "$CONTAINER_NAME_CACHE" ] && declare -p CONTAINER_NAME_CACHE &>/dev/null; then
        CONTAINER_NAME_CACHE[$service]="$container_name"
    fi
    
    echo "$container_name"
}

# Get all services (with caching)
get_all_services() {
    local current_time=$(date +%s)
    
    # Check if cache is valid
    if [ -n "$SERVICES_CACHE" ] && [ $((current_time - SERVICES_CACHE_TIME)) -lt $CACHE_DURATION ]; then
        echo "$SERVICES_CACHE"
        return
    fi
    
    # Fetch and cache services
    SERVICES_CACHE=$($DOCKER_COMPOSE config --services 2>/dev/null)
    SERVICES_CACHE_TIME=$current_time
    
    echo "$SERVICES_CACHE"
}

# Get service health status (unified format)
get_service_health() {
    local container="$1"
    
    # Check if container exists first
    if ! docker ps -a --format "{{.Names}}" | grep -q "^${container}$"; then
        echo "not_found"
        return
    fi
    
    # Get health status
    local health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{if .State.Running}}running{{else}}stopped{{end}}{{end}}' \
        "$container" 2>/dev/null || echo "error")
    
    echo "$health"
}

# Check if service is running (returns exit code)
is_service_running() {
    local service="$1"
    local container_name=$(get_container_name "$service")
    
    # Check if container is running
    docker ps --format "{{.Names}}" 2>/dev/null | grep -q "^${container_name}$"
}

# Get service status with details
get_service_status() {
    local service="$1"
    local container_name=$(get_container_name "$service")
    
    # Check if running
    if docker ps --format "{{.Names}}" | grep -q "^${container_name}$"; then
        local health=$(get_service_health "$container_name")
        echo "running:$health"
    elif docker ps -a --format "{{.Names}}" | grep -q "^${container_name}$"; then
        echo "stopped"
    else
        echo "not_created"
    fi
}

# Get container logs (last N lines)
get_container_logs() {
    local container="$1"
    local lines="${2:-50}"
    
    docker logs --tail "$lines" "$container" 2>&1
}

# Get container stats (CPU, Memory)
get_container_stats() {
    local container="$1"
    
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" "$container" 2>/dev/null
}

# ============================================================================
# Batch Operations
# ============================================================================

# Get status of all services
get_all_services_status() {
    local services=$(get_all_services)
    
    for service in $services; do
        local status=$(get_service_status "$service")
        echo "$service:$status"
    done
}

# Check if all required services are running
check_required_services() {
    local required_services="${1:-db redis}"
    local all_running=true
    
    for service in $required_services; do
        if ! is_service_running "$service"; then
            all_running=false
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${RED}✗${NC} $service is not running"
            fi
        fi
    done
    
    $all_running
}

# ============================================================================
# Docker Compose Operations
# ============================================================================

# Parse docker-compose.yml efficiently (cached)
parse_compose_config() {
    local query="$1"
    local cache_file="${ALETHEIA_TEMP}/compose_cache"
    
    # Cache the full config if not already cached
    if [ ! -f "$cache_file" ]; then
        $DOCKER_COMPOSE config 2>/dev/null > "$cache_file"
    fi
    
    # Query the cached config
    grep "$query" "$cache_file"
}

# Get service dependencies
get_service_dependencies() {
    local service="$1"
    local deps=""
    
    # Parse both simple and extended depends_on format
    local config=$(parse_compose_config "^  $service:" | head -20)
    
    # Check for depends_on
    if echo "$config" | grep -q "depends_on:"; then
        # Simple format: depends_on: [db, redis]
        deps=$(echo "$config" | grep -A 10 "depends_on:" | \
               grep "^    - " | sed 's/^    - //')
        
        # Extended format: depends_on: db: condition: service_started
        if [ -z "$deps" ]; then
            deps=$(echo "$config" | grep -A 10 "depends_on:" | \
                   grep "^      " | grep -v "condition:" | \
                   sed 's/^      //' | sed 's/://')
        fi
    fi
    
    echo "$deps"
}

# ============================================================================
# Cleanup Operations
# ============================================================================

# Clean up orphaned containers from previous sessions
cleanup_orphaned_containers() {
    if ! command -v docker &>/dev/null || ! docker ps &>/dev/null 2>&1; then
        return 0  # Docker not available, skip
    fi
    
    local compose_containers
    local all_project_containers
    
    # Get containers that docker-compose knows about
    compose_containers=$($DOCKER_COMPOSE ps -q 2>/dev/null || true)
    
    # Get all containers with our project label
    all_project_containers=$(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT_NAME}" 2>/dev/null || true)
    
    if [ -z "$all_project_containers" ]; then
        return 0  # No containers to check
    fi
    
    local orphaned_count=0
    for container in $all_project_containers; do
        if [ -z "$compose_containers" ] || ! echo "$compose_containers" | grep -q "$container"; then
            local container_name=$(docker inspect --format='{{.Name}}' "$container" 2>/dev/null | sed 's/^\/*//')
            if [ -n "$container_name" ]; then
                echo -e "${YELLOW}Removing orphaned container: $container_name${NC}"
                docker rm -f "$container" &>/dev/null
                orphaned_count=$((orphaned_count + 1))
            fi
        fi
    done
    
    if [ $orphaned_count -gt 0 ]; then
        echo -e "${GREEN}✓ Cleaned up $orphaned_count orphaned container(s)${NC}"
    fi
}

# Clean up session caches
cleanup_docker_caches() {
    # Caches are now in ALETHEIA_TEMP which is cleaned up by dev-lib.sh
    # This function is kept for backwards compatibility
    return 0
}

# Note: Cleanup is handled by dev-lib.sh cleanup_session()

# Run cleanup on module load
cleanup_orphaned_containers

# ============================================================================
# Export Functions
# ============================================================================

export -f get_container_name
export -f get_all_services
export -f get_service_health
export -f is_service_running
export -f get_service_status
export -f get_container_logs
export -f get_container_stats
export -f get_all_services_status
export -f check_required_services
export -f parse_compose_config
export -f get_service_dependencies
export -f cleanup_docker_caches
export -f cleanup_orphaned_containers