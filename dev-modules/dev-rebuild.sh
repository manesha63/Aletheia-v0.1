#!/bin/bash

# ============================================================================
# Dev CLI Rebuild Module
# ============================================================================
# This module handles Docker service rebuilding

# Handle rebuild command
handle_rebuild_command() {
    utils_rebuild "$@"
}

# Rebuild services
utils_rebuild() {
    check_requirements
    check_env
    
    # Parse arguments - support both old flags and new subcommands
    SERVICE=""
    HARD_CLEAN=false
    VERIFY=false
    
    for arg in "$@"; do
        case "$arg" in
            --hard|hard)
                HARD_CLEAN=true
                ;;
            --verify|verify)
                VERIFY=true
                ;;
            -*)
                echo -e "${RED}Unknown option: $arg${NC}"
                echo "Usage: ./dev rebuild [service|hard|verify]"
                echo "Examples:"
                echo "  ./dev rebuild              # Rebuild all services"
                echo "  ./dev rebuild n8n          # Rebuild specific service"
                echo "  ./dev rebuild hard         # Hard rebuild (aggressive cache clear)"
                echo "  ./dev rebuild hard verify  # Hard rebuild with verification"
                return $EXIT_CONFIG_ERROR
                ;;
            *)
                # Check if it's a service name or a command
                if [ "$arg" = "hard" ] || [ "$arg" = "verify" ]; then
                    # Already handled above
                    :
                elif [ -z "$SERVICE" ]; then
                    SERVICE="$arg"
                fi
                ;;
        esac
    done
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Docker Service Rebuild"
        
        # Determine what to rebuild
        if [ -n "$SERVICE" ]; then
            echo -e "${CYAN}Target:${NC} $SERVICE"
        else
            echo -e "${CYAN}Target:${NC} All services"
        fi
        
        if [ "$HARD_CLEAN" = true ]; then
            echo -e "${CYAN}Mode:${NC} Hard clean (aggressive cache clearing)"
        else
            echo -e "${CYAN}Mode:${NC} Standard rebuild"
        fi
        echo ""
    fi
    
    # Step 1: Stop services
    if [ -n "$SERVICE" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 1: Stopping $SERVICE..."
        fi
        $DOCKER_COMPOSE stop "$SERVICE" &>/dev/null
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 1: Stopping all services..."
        fi
        $DOCKER_COMPOSE down &>/dev/null
    fi
    
    # Step 2: Remove containers and images
    if [ "$HARD_CLEAN" = true ]; then
        if [ -n "$SERVICE" ]; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo "Step 2: Removing $SERVICE container and image..."
            fi
            $DOCKER_COMPOSE rm -f "$SERVICE" &>/dev/null
            
            # Remove the specific service image
            image_name=$($DOCKER_COMPOSE config | grep -A 5 "^  $SERVICE:" | grep "image:" | awk '{print $2}')
            if [ -n "$image_name" ]; then
                docker rmi -f "$image_name" &>/dev/null || true
            fi
            
            # Clear builder cache for this service
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo "  • Clearing builder cache"
            fi
            docker builder prune -f --filter "label=com.docker.compose.project=${PROJECT_NAME}" &>/dev/null
        else
            # Full system cleanup
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo "  • Removing all project images"
            fi
            docker-compose down --rmi all &>/dev/null || true
            
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo "  • Clearing all builder cache"
            fi
            docker builder prune -af &>/dev/null
        fi
    fi
    
    # Step 3: Rebuild
    if [ -n "$SERVICE" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 3: Rebuilding $SERVICE..."
        fi
        $DOCKER_COMPOSE build --no-cache "$SERVICE"
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 3: Rebuilding all services..."
        fi
        $DOCKER_COMPOSE build --no-cache
    fi
    
    # Step 4: Start services
    if [ -n "$SERVICE" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 4: Starting $SERVICE..."
        fi
        $DOCKER_COMPOSE up -d "$SERVICE"
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo "Step 4: Starting services..."
        fi
        $DOCKER_COMPOSE up -d
    fi
    
    # Step 5: Verify
    if [ "$VERIFY" = true ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo ""
            echo "Step 5: Verifying rebuild..."
        fi
        sleep 5  # Give services time to start
        
        if [ -n "$SERVICE" ]; then
            if check_service_running "$SERVICE" true; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓ $SERVICE is running${NC}"
                fi
            else
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${RED}✗ $SERVICE failed to start${NC}"
                fi
                return $EXIT_SERVICE_UNAVAILABLE
            fi
        else
            # Call the health check using new check command
            handle_check_command --health
        fi
    fi
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{"status":"success","message":"Rebuild complete"}'
    else
        echo ""
        echo -e "${GREEN}✓ Rebuild complete${NC}"
    fi
}

# Export functions
export -f handle_rebuild_command
export -f utils_rebuild