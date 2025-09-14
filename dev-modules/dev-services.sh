#!/bin/bash

# ============================================================================
# Dev CLI Service Management Module
# ============================================================================
# This module contains commands for managing Docker Compose services

# Ensure Docker UID/GID are set correctly for different use cases
ensure_docker_uid_gid() {
    if [ -f .env ]; then
        local actual_uid=$(id -u)
        local actual_gid=$(id -g)
        local needs_update=false
        
        # Validate that we got numeric UID/GID
        if ! [[ "$actual_uid" =~ ^[0-9]+$ ]] || ! [[ "$actual_gid" =~ ^[0-9]+$ ]]; then
            echo -e "${RED}✗ Failed to get valid UID/GID from system${NC}"
            return 1
        fi
        
        # Check if host UID/GID variables are missing or incorrect for the platform
        local current_host_uid=$(grep "^DOCKER_UID=" .env | cut -d= -f2)
        if [ -z "$current_host_uid" ] || [ "$current_host_uid" != "$actual_uid" ]; then
            needs_update=true
        fi
        
        # Check if container UID/GID variables are missing (for tmpfs mounts)
        local current_n8n_uid=$(grep "^N8N_CONTAINER_UID=" .env | cut -d= -f2)
        if [ -z "$current_n8n_uid" ]; then
            needs_update=true
        fi
        
        if [ "$needs_update" = true ]; then
            echo -e "${YELLOW}Configuring Docker UID/GID for your platform...${NC}"
            
            # Remove old entries if they exist
            sed -i.bak '/^DOCKER_UID=/d' .env 2>/dev/null || sed -i '' '/^DOCKER_UID=/d' .env
            sed -i.bak '/^DOCKER_GID=/d' .env 2>/dev/null || sed -i '' '/^DOCKER_GID=/d' .env
            sed -i.bak '/^N8N_CONTAINER_UID=/d' .env 2>/dev/null || sed -i '' '/^N8N_CONTAINER_UID=/d' .env
            sed -i.bak '/^N8N_CONTAINER_GID=/d' .env 2>/dev/null || sed -i '' '/^N8N_CONTAINER_GID=/d' .env
            
            # Append correct values
            echo "" >> .env
            echo "# Docker UID/GID configuration (platform-specific)" >> .env
            echo "# Host UID/GID for file mounts (matches your user)" >> .env
            echo "DOCKER_UID=$actual_uid" >> .env
            echo "DOCKER_GID=$actual_gid" >> .env
            echo "# Container UID/GID for tmpfs mounts (matches container users)" >> .env
            echo "N8N_CONTAINER_UID=1000" >> .env
            echo "N8N_CONTAINER_GID=1000" >> .env
            
            echo -e "${GREEN}✓ Host UID/GID: $actual_uid/$actual_gid (for file mounts, matches your user)${NC}"
            echo -e "${GREEN}✓ Container UID/GID: 1000/1000 (for tmpfs mounts, matches container users)${NC}"
            
            # Clean up backup files
            rm -f .env.bak 2>/dev/null
        fi
    fi
}

# Ensure services are ready (dependencies installed, builds complete)
ensure_services_ready() {
    local NEEDS_SETUP=false
    
    # Check if lawyer-chat needs setup
    if [ -d "services/lawyer-chat" ]; then
        if [ ! -d "services/lawyer-chat/node_modules" ] || [ ! -d "services/lawyer-chat/.next" ]; then
            NEEDS_SETUP=true
        fi
    fi
    
    # Check if ai-portal needs setup
    if [ -d "services/ai-portal" ]; then
        if [ ! -d "services/ai-portal/node_modules" ] || [ ! -d "services/ai-portal/.next" ]; then
            NEEDS_SETUP=true
        fi
    fi
    
    if [ "$NEEDS_SETUP" = true ]; then
        echo -e "${YELLOW}Services need initial setup...${NC}"
        echo ""
        
        # Install and build lawyer-chat if needed
        if [ -d "services/lawyer-chat" ]; then
            if [ ! -d "services/lawyer-chat/node_modules" ]; then
                echo -e "${CYAN}Installing lawyer-chat dependencies...${NC}"
                cd services/lawyer-chat
                if npm install &>/dev/null; then
                    echo -e "${GREEN}✓ Lawyer-chat dependencies installed${NC}"
                    
                    # Generate Prisma client
                    if npx prisma generate &>/dev/null; then
                        echo -e "${GREEN}✓ Prisma client generated${NC}"
                    fi
                else
                    echo -e "${YELLOW}⚠ Failed to install lawyer-chat dependencies${NC}"
                fi
                cd - &>/dev/null
            fi
            
            if [ ! -d "services/lawyer-chat/.next" ]; then
                echo -e "${CYAN}Building lawyer-chat...${NC}"
                cd services/lawyer-chat
                if npm run build &>/dev/null; then
                    echo -e "${GREEN}✓ Lawyer-chat built successfully${NC}"
                else
                    echo -e "${YELLOW}⚠ Failed to build lawyer-chat${NC}"
                fi
                cd - &>/dev/null
            fi
        fi
        
        # Install and build ai-portal if needed
        if [ -d "services/ai-portal" ]; then
            if [ ! -d "services/ai-portal/node_modules" ]; then
                echo -e "${CYAN}Installing ai-portal dependencies...${NC}"
                cd services/ai-portal
                if npm install &>/dev/null; then
                    echo -e "${GREEN}✓ AI-portal dependencies installed${NC}"
                else
                    echo -e "${YELLOW}⚠ Failed to install ai-portal dependencies${NC}"
                fi
                cd - &>/dev/null
            fi
            
            if [ ! -d "services/ai-portal/.next" ]; then
                echo -e "${CYAN}Building ai-portal...${NC}"
                cd services/ai-portal
                if npm run build &>/dev/null; then
                    echo -e "${GREEN}✓ AI-portal built successfully${NC}"
                else
                    echo -e "${YELLOW}⚠ Failed to build ai-portal${NC}"
                fi
                cd - &>/dev/null
            fi
        fi
        
        echo ""
    fi
}

# Handle service commands
handle_service_command() {
    local cmd="$1"
    shift
    
    case "$cmd" in
        up|start)
            service_up "$@"
            ;;
        down|stop)
            service_down "$@"
            ;;
        restart)
            service_restart "$@"
            ;;
        status|ps)
            service_status "$@"
            ;;
        logs|log)
            service_logs "$@"
            ;;
        shell|exec)
            service_shell "$@"
            ;;
        purge)
            service_purge "$@"
            ;;
        *)
            # If not a subcommand, it might be a main command
            return 1
            ;;
    esac
}

# Start services
service_up() {
    local service="$1"
    
    check_requirements
    check_env
    
    # Ensure Docker UID/GID are correct (critical for macOS)
    ensure_docker_uid_gid
    
    # Check if services need initial setup (only for full startup)
    if [ -z "$service" ]; then
        ensure_services_ready
    fi
    
    # Check if specific service requested
    if [ -n "$service" ]; then
        echo -e "${BLUE}Starting $service...${NC}"
        if $DOCKER_COMPOSE up -d "$service" 2>&1 | grep -q "no such service"; then
            echo -e "${RED}✗ Service $service does not exist${NC}"
            return $EXIT_CONFIG_ERROR
        else
            echo -e "${GREEN}✓ Service $service started${NC}"
        fi
    else
        echo -e "${BLUE}Starting all Aletheia services...${NC}"
        # Start all services defined in docker-compose.yml
        $DOCKER_COMPOSE up -d
        echo ""
        echo -e "${GREEN}✓ Services started successfully!${NC}"
        echo ""
        echo "Access points:"
        echo "  • Main app:     http://localhost:${WEB_PORT:-8080}"
        echo "  • n8n:          http://localhost:${N8N_PORT:-8100}"
        echo "            Note: Check n8n/README.md for credentials"
        echo "  • Lawyer Chat:  http://localhost:${WEB_PORT:-8080}/chat"
        echo "  • AI Portal:    http://localhost:${AI_PORTAL_PORT:-8102}"
        echo ""
        echo "Run './dev logs' to see output"
        echo "Run './dev health' to check services"
        
        # Wait for database to be ready (max 30 seconds)
        DB_READY=false
        for i in {1..30}; do
            if $DOCKER_COMPOSE exec -T db pg_isready -U "${DB_USER:-aletheia}" &>/dev/null; then
                DB_READY=true
                break
            fi
            if [ $i -eq 1 ]; then
                echo ""
                echo -n "Waiting for database to be ready"
            else
                echo -n "."
            fi
            sleep 1
        done
        
        if [ "$DB_READY" = true ]; then
            echo ""  # New line after dots
            
            # Auto-restore court data if it's a fresh database
            if [ -f court-processor/data/court_documents_backup.sql.gz ]; then
                echo ""
                echo -e "${BLUE}Checking for court processor data...${NC}"
                
                # Wait for court_documents table to be created by init script (max 10 seconds)
                TABLE_EXISTS=false
                for i in {1..10}; do
                    if $DOCKER_COMPOSE exec -T -e PGPASSWORD="${DB_PASSWORD}" db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" -c "\dt court_documents" 2>&1 | grep -q court_documents; then
                        TABLE_EXISTS=true
                        break
                    fi
                    sleep 1
                done
                
                if [ "$TABLE_EXISTS" = false ]; then
                    echo -e "${YELLOW}⚠ Court documents table not found (database initialization may still be running)${NC}"
                else
                    # Check if court_documents table exists and count records
                    COUNT=$($DOCKER_COMPOSE exec -T -e PGPASSWORD="${DB_PASSWORD}" db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" -t -c \
                        "SELECT COUNT(*) FROM public.court_documents" 2>/dev/null || echo "0")
                COUNT=$(echo $COUNT | tr -d ' ')
                
                if [ "$COUNT" = "0" ]; then
                    echo -e "${BLUE}Restoring court processor sample data (485 documents)...${NC}"
                    if gunzip -c court-processor/data/court_documents_backup.sql.gz | \
                       $DOCKER_COMPOSE exec -T -e PGPASSWORD="${DB_PASSWORD}" db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" >/dev/null 2>&1; then
                        echo -e "${GREEN}✓ Successfully restored 485 court documents${NC}"
                        echo "  Documents are now available in Lawyer Chat interface"
                    else
                        echo -e "${YELLOW}⚠ Failed to restore court data${NC}"
                        echo "  You can manually restore with: ./dev db restore-court-data"
                    fi
                elif [ "$COUNT" -gt "0" ]; then
                    echo -e "${GREEN}✓ Database already contains $COUNT court documents${NC}"
                fi
                fi  # Close TABLE_EXISTS check
            fi
            
            # Auto-initialize lawyer-chat database and seed demo users
            echo ""
            echo -e "${BLUE}Checking lawyer-chat database setup...${NC}"
            
            # Check if User table exists
            USER_TABLE_EXISTS=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d lawyerchat -t -c \
                "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'User');" 2>/dev/null | tr -d ' ')
            
            if [ "$USER_TABLE_EXISTS" = "f" ] || [ "$USER_TABLE_EXISTS" = "false" ] || [ -z "$USER_TABLE_EXISTS" ]; then
                echo -e "${BLUE}Initializing lawyer-chat database...${NC}"
                
                # Drop any conflicting views that might prevent Prisma from syncing
                $DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d lawyerchat -c \
                    "DROP VIEW IF EXISTS workflow_summary_stats CASCADE;" &>/dev/null 2>&1
                
                # Check if lawyer-chat service directory exists
                if [ -d "services/lawyer-chat" ]; then
                    cd services/lawyer-chat
                    
                    # URL-encode the password to handle special characters
                    ENCODED_PASSWORD=$(url_encode "${DB_PASSWORD}")
                    export DATABASE_URL="postgresql://${DB_USER:-aletheia}:${ENCODED_PASSWORD}@localhost:${POSTGRES_PORT:-8200}/lawyerchat"
                    
                    if npx prisma db push --skip-generate &>/dev/null 2>&1; then
                        echo -e "${GREEN}✓ Database schema created${NC}"
                        
                        # Generate Prisma client
                        if npx prisma generate &>/dev/null 2>&1; then
                            echo -e "${GREEN}✓ Prisma client generated${NC}"
                            
                            # Seed demo users - Always use SQL insertion as it's more reliable
                            echo -e "${BLUE}Creating demo users...${NC}"
                            # These are the CORRECT hashes for demo123 and admin123 (verified with bcryptjs)
                            DEMO_HASH='$2a$12$FlggC69ExCZaqqaLv.d6gOfWIZJbRdLtfAfNz/dZw0JTohCblKliq'
                            ADMIN_HASH='$2a$12$B3GQNcs5JCDCBKA3zpxBG.r5ESM75LTtdAiqChGlFoUf3g6F8A9zq'
                            
                            if $DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d lawyerchat -c \
                                "INSERT INTO \"User\" (id, email, name, password, role, \"emailVerified\", \"createdAt\", \"updatedAt\") 
                                 VALUES ('demo-'||gen_random_uuid(), 'demo@reichmanjorgensen.com', 'Demo User', '${DEMO_HASH}', 'USER', NOW(), NOW(), NOW()),
                                        ('admin-'||gen_random_uuid(), 'admin@reichmanjorgensen.com', 'Admin User', '${ADMIN_HASH}', 'ADMIN', NOW(), NOW(), NOW()) 
                                 ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password, \"updatedAt\" = NOW();" &>/dev/null 2>&1; then
                                echo -e "${GREEN}✓ Demo users created:${NC}"
                                echo "    • demo@reichmanjorgensen.com / demo123"
                                echo "    • admin@reichmanjorgensen.com / admin123"
                            else
                                echo -e "${YELLOW}⚠ Could not create demo users (may already exist)${NC}"
                            fi
                        else
                            echo -e "${YELLOW}⚠ Failed to generate Prisma client${NC}"
                        fi
                    else
                        echo -e "${YELLOW}⚠ Failed to initialize database schema${NC}"
                        echo "  You can manually run: cd services/lawyer-chat && npx prisma db push"
                    fi
                    
                    cd - &>/dev/null
                else
                    echo -e "${YELLOW}⚠ Lawyer-chat service directory not found${NC}"
                fi
            else
                # Check if demo users exist
                USER_COUNT=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d lawyerchat -t -c \
                    "SELECT COUNT(*) FROM \"User\" WHERE email IN ('demo@reichmanjorgensen.com', 'admin@reichmanjorgensen.com');" 2>/dev/null | tr -d ' ')
                
                if [ "$USER_COUNT" = "0" ] || [ -z "$USER_COUNT" ]; then
                    echo -e "${BLUE}Seeding demo users...${NC}"
                    
                    # Seed demo users directly in database with CORRECT bcrypt hashes
                    # These are verified hashes for demo123 and admin123 with cost factor 12
                    DEMO_HASH='$2a$12$FlggC69ExCZaqqaLv.d6gOfWIZJbRdLtfAfNz/dZw0JTohCblKliq'
                    ADMIN_HASH='$2a$12$B3GQNcs5JCDCBKA3zpxBG.r5ESM75LTtdAiqChGlFoUf3g6F8A9zq'
                    
                    if $DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d lawyerchat -c \
                        "INSERT INTO \"User\" (id, email, name, password, role, \"emailVerified\", \"createdAt\", \"updatedAt\") 
                         VALUES ('demo-user-'||gen_random_uuid(), 'demo@reichmanjorgensen.com', 'Demo User', '${DEMO_HASH}', 'USER', NOW(), NOW(), NOW()),
                                ('admin-user-'||gen_random_uuid(), 'admin@reichmanjorgensen.com', 'Admin User', '${ADMIN_HASH}', 'ADMIN', NOW(), NOW(), NOW()) 
                         ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password, \"updatedAt\" = NOW();" &>/dev/null 2>&1; then
                        echo -e "${GREEN}✓ Demo users created:${NC}"
                        echo "    • demo@reichmanjorgensen.com / demo123"
                        echo "    • admin@reichmanjorgensen.com / admin123"
                    else
                        echo -e "${YELLOW}⚠ Failed to seed demo users (may already exist)${NC}"
                    fi
                else
                    echo -e "${GREEN}✓ Lawyer-chat database ready ($USER_COUNT demo users found)${NC}"
                    # Verify credentials are working
                    if command -v verify_credentials &>/dev/null; then
                        verify_credentials
                    fi
                fi
            fi
        else
            echo ""  # New line after dots
            echo -e "${YELLOW}⚠ Database not ready${NC}"
            echo "  Database initialization skipped - run './dev up' again when ready"
        fi
    fi
    
    # Initialize n8n after services are up
    if [ -z "$service" ] && [ "$DB_READY" = true ]; then
        initialize_n8n_setup
    fi
}

# Initialize n8n with credentials and workflows
initialize_n8n_setup() {
    echo ""
    echo -e "${BLUE}Initializing n8n automation platform...${NC}"
    
    # Wait for n8n to be ready (max 60 seconds)
    N8N_READY=false
    for i in {1..60}; do
        if docker exec aletheia_development-n8n-1 test -f /data/.n8n/database.sqlite 2>/dev/null; then
            # Check if database has settings table
            if docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite "SELECT name FROM sqlite_master WHERE type='table' AND name='settings';" 2>/dev/null | grep -q settings; then
                N8N_READY=true
                break
            fi
        fi
        if [ $i -eq 1 ]; then
            echo -n "  Waiting for n8n to initialize"
        else
            echo -n "."
        fi
        sleep 1
    done
    
    if [ "$N8N_READY" = true ]; then
        echo ""  # New line after dots
        
        # Get the project ID for the n8n user
        PROJECT_ID=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
            "SELECT projectId FROM project_relation WHERE role='project:personalOwner' LIMIT 1;" 2>/dev/null)
        
        if [ -z "$PROJECT_ID" ]; then
            PROJECT_ID="personal-auto-setup-user"
        fi
        
        # Configure n8n credentials using the reliable credential management system
        echo -e "${BLUE}Configuring n8n credentials...${NC}"
        
        # Run credential manager to create and link credentials 
        if [ -n "${ANTHROPIC_API_KEY}" ] || [ -n "${DB_PASSWORD}" ]; then
            # Use the reliable credential management system
            if docker exec aletheia_development-n8n-1 sh -c "cd /scripts && ANTHROPIC_API_KEY='${ANTHROPIC_API_KEY}' ./manage-credentials.sh" &>/dev/null 2>&1; then
                echo -e "${GREEN}✓ Credentials configured successfully${NC}"
                
                # Restart n8n to reload workflows with updated credentials
                echo -e "${BLUE}Restarting n8n to apply credential changes...${NC}"
                docker restart aletheia_development-n8n-1 &>/dev/null
                
                # Wait for n8n to be ready again (needs more time after restart)
                sleep 20
                
                # Test webhook if Anthropic key is present
                if [ -n "${ANTHROPIC_API_KEY}" ]; then
                    echo -e "${BLUE}Testing n8n webhook...${NC}"
                    
                    # Test webhook with a simple request
                    WEBHOOK_RESPONSE=$(curl -s -X POST \
                        "http://localhost:${N8N_PORT:-8100}/webhook/${N8N_WEBHOOK_ID:-c188c31c-1c45-4118-9ece-5b6057ab5177}" \
                        -H "Content-Type: application/json" \
                        -d '{"sessionKey":"test","message":"Hello"}' \
                        --max-time 15 2>/dev/null || echo "")
                    
                    if [ -n "$WEBHOOK_RESPONSE" ] && [ "$WEBHOOK_RESPONSE" != "{}" ]; then
                        echo -e "${GREEN}✓ n8n webhook is functional (AI responding)${NC}"
                    else
                        echo -e "${YELLOW}⚠ n8n webhook returned empty response${NC}"
                        echo "  This may mean credentials need manual configuration in n8n UI"
                    fi
                fi
            else
                echo -e "${YELLOW}⚠ Could not configure credentials${NC}"
                echo "  You may need to manually configure credentials in n8n UI"
            fi
        fi
        
        echo -e "${GREEN}✓ n8n is ready at http://localhost:${N8N_PORT:-8100}${NC}"
        echo "    Login: velvetmoon222999@gmail.com / admin123"
    else
        echo ""  # New line after dots
        echo -e "${YELLOW}⚠ n8n initialization taking longer than expected${NC}"
        echo "  You can manually check status with: ./dev n8n status"
    fi
}

# Stop services
service_down() {
    local service="$1"
    
    check_requirements
    
    # Check if specific service requested
    if [ -n "$service" ]; then
        echo -e "${BLUE}Stopping $service...${NC}"
        $DOCKER_COMPOSE stop "$service"
        echo -e "${GREEN}✓ Service $service stopped${NC}"
    else
        echo -e "${BLUE}Stopping all Aletheia services...${NC}"
        $DOCKER_COMPOSE down
        echo -e "${GREEN}✓ All services stopped${NC}"
    fi
}

# Restart services
service_restart() {
    local service="$1"
    
    check_requirements
    if [ -z "$service" ]; then
        echo -e "${BLUE}Restarting all services...${NC}"
        $DOCKER_COMPOSE restart
    else
        echo -e "${BLUE}Restarting $service...${NC}"
        $DOCKER_COMPOSE restart "$service"
    fi
    echo -e "${GREEN}✓ Restart complete${NC}"
}

# Show service status
service_status() {
    local mode="full"  # Default mode
    local verbose=false
    
    # Parse arguments - support both old flags and new subcommands
    for arg in "$@"; do
        case "$arg" in
            --explain|explain)
                mode="explain"
                ;;
            --simple|simple)
                mode="simple"
                ;;
            --verbose|-v|verbose)
                verbose=true
                ;;
            *)
                # If first arg is a mode name, use it
                if [ "$arg" = "$1" ]; then
                    case "$arg" in
                        simple|explain|full)
                            mode="$arg"
                            ;;
                    esac
                fi
                ;;
        esac
    done
    
    # Set flags based on mode for backward compatibility
    local explain=false
    local simple=false
    case "$mode" in
        explain)
            explain=true
            ;;
        simple)
            simple=true
            ;;
    esac
    
    check_requirements
    
    # Simple mode - just show service-level health (like old health command)
    if [ "$simple" = true ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            print_header "Service Health Status"
            echo -e "${CYAN}Services:${NC}"
        fi
        
        # Get all services and show simple status
        local all_services=$(get_all_services)
        local healthy=0
        local unhealthy=0
        
        for service in $all_services; do
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
        
        return
    fi
    
    # Regular detailed mode
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Service Status"
        
        # Container status
        echo -e "${CYAN}Containers:${NC}"
        $DOCKER_COMPOSE ps -a --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        
        # Health status
        echo -e "${CYAN}Health Status:${NC}"
    fi
    
    healthy=0
    unhealthy=0
    nocheck=0
    services_json="["
    first=true
    
    for container in $(docker ps -a --format "{{.Names}}" --filter "label=com.docker.compose.project=${PROJECT_NAME}"); do
        # Special handling for known containers without standard health checks
        if [[ "$container" == *"recap-webhook"* ]]; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${YELLOW}○${NC} $container: health check ignored"
            fi
            nocheck=$((nocheck + 1))
            continue
        fi
        
        # Check if container is running
        container_state=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "error")
        
        if [ "$container_state" = "exited" ] || [ "$container_state" = "stopped" ]; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                local exit_code=$(docker inspect --format='{{.State.ExitCode}}' "$container" 2>/dev/null)
                echo -e "${RED}✗${NC} $container: stopped/exited (exit code: $exit_code)"
                
                # Show explanation if requested
                if [ "$explain" = true ]; then
                    echo -e "    ${CYAN}Stopped at:${NC} $(docker inspect --format='{{.State.FinishedAt}}' "$container" 2>/dev/null | cut -d'T' -f1,2)"
                    
                    # Get last logs
                    local last_logs=$(docker logs "$container" 2>&1 | tail -5)
                    if [ -n "$last_logs" ]; then
                        echo -e "    ${CYAN}Last logs:${NC}"
                        echo "$last_logs" | sed 's/^/      /'
                    fi
                    
                    # Common exit code explanations
                    case "$exit_code" in
                        0)
                            echo -e "    ${GREEN}Exit code 0:${NC} Clean shutdown"
                            ;;
                        1)
                            echo -e "    ${RED}Exit code 1:${NC} General application error"
                            ;;
                        125)
                            echo -e "    ${RED}Exit code 125:${NC} Docker run command failed"
                            ;;
                        126)
                            echo -e "    ${RED}Exit code 126:${NC} Container command not executable"
                            ;;
                        127)
                            echo -e "    ${RED}Exit code 127:${NC} Container command not found"
                            ;;
                        137)
                            echo -e "    ${YELLOW}Exit code 137:${NC} Container killed (SIGKILL) - possibly OOM"
                            ;;
                        143)
                            echo -e "    ${YELLOW}Exit code 143:${NC} Container terminated (SIGTERM)"
                            ;;
                    esac
                fi
            fi
            unhealthy=$((unhealthy + 1))
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                if [ "$first" = true ]; then
                    first=false
                else
                    services_json="${services_json},"
                fi
                services_json="${services_json}{\"name\":\"$container\",\"health\":\"stopped\"}"
            fi
            continue
        fi
        
        # Get health status using shared function
        health=$(get_service_health "$container")
        
        case "$health" in
            healthy)
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓${NC} $container: healthy"
                fi
                healthy=$((healthy + 1))
                health_json="\"healthy\""
                ;;
            unhealthy|starting)
                # Skip recap-webhook unhealthy status as it's expected
                if [[ "$container" != *"recap-webhook"* ]]; then
                    if [ "$OUTPUT_FORMAT" != "json" ]; then
                        echo -e "${RED}✗${NC} $container: $health"
                        
                        # Show explanation if requested
                        if [ "$explain" = true ]; then
                            # Get health check logs
                            local health_log=$(docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' "$container" 2>/dev/null | tail -1)
                            if [ -n "$health_log" ]; then
                                echo -e "    ${CYAN}Health check output:${NC} $health_log"
                            fi
                            
                            # Get last container logs
                            local last_logs=$(docker logs "$container" 2>&1 | tail -3)
                            if [ -n "$last_logs" ]; then
                                echo -e "    ${CYAN}Recent logs:${NC}"
                                echo "$last_logs" | sed 's/^/      /'
                            fi
                        fi
                    fi
                    unhealthy=$((unhealthy + 1))
                fi
                health_json="\"$health\""
                ;;
            "no check"|"")
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${YELLOW}○${NC} $container: no health check"
                fi
                nocheck=$((nocheck + 1))
                health_json="\"no_check\""
                ;;
            error)
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${RED}✗${NC} $container: inspection failed"
                fi
                unhealthy=$((unhealthy + 1))
                health_json="\"error\""
                ;;
        esac
        
        # Build JSON array
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            if [ "$first" = true ]; then
                first=false
            else
                services_json="${services_json},"
            fi
            services_json="${services_json}{\"name\":\"$container\",\"health\":$health_json}"
        fi
    done
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        services_json="${services_json}]"
        echo "{\"healthy\":$healthy,\"unhealthy\":$unhealthy,\"nocheck\":$nocheck,\"services\":$services_json}"
    else
        echo ""
        echo -e "Summary: ${GREEN}$healthy healthy${NC}, ${RED}$unhealthy issues${NC}, ${YELLOW}$nocheck unchecked${NC}"
    fi
}

# Show service logs
service_logs() {
    local service="$1"
    
    check_requirements
    if [ -z "$service" ]; then
        $DOCKER_COMPOSE logs -f --tail=100
    else
        $DOCKER_COMPOSE logs -f --tail=100 "$service"
    fi
}

# Open shell in container
service_shell() {
    local service="$1"
    
    check_requirements
    if [ -z "$service" ]; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"error","message":"Service name required"}'
        else
            echo -e "${RED}Please specify a service name${NC}"
            echo "Example: ./dev shell db"
        fi
        exit $EXIT_CONFIG_ERROR
    fi
    
    case "$service" in
        db|postgres)
            echo -e "${BLUE}Opening PostgreSQL shell...${NC}"
            $DOCKER_COMPOSE exec db psql -U "${DB_USER:-aletheia}" "${DB_NAME:-aletheia}"
            ;;
        n8n)
            echo -e "${BLUE}Opening n8n shell...${NC}"
            $DOCKER_COMPOSE exec n8n /bin/sh
            ;;
        *)
            echo -e "${BLUE}Opening shell in $service...${NC}"
            $DOCKER_COMPOSE exec "$service" /bin/sh 2>/dev/null || $DOCKER_COMPOSE exec "$service" /bin/bash
            ;;
    esac
}

# List available services
service_list() {
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        # Get services using shared function
        services=$(get_all_services)
        if [ -z "$services" ]; then
            echo '{"status":"error","message":"No services found"}'
        else
            echo -n '{"status":"success","services":['
            first=true
            while IFS= read -r service; do
                if [ "$first" = true ]; then
                    first=false
                else
                    echo -n ','
                fi
                echo -n "\"$service\""
            done <<< "$services"
            echo ']}'
        fi
    else
        echo -e "${BLUE}Available Services:${NC}"
        get_all_services | while read service; do
            # Check if service is running
            if $DOCKER_COMPOSE ps "$service" 2>/dev/null | grep -q "Up\|Running"; then
                echo -e "  ${GREEN}●${NC} $service (running)"
            else
                echo -e "  ${YELLOW}○${NC} $service (stopped)"
            fi
        done
    fi
}

# Purge services and volumes (destructive - deletes all data)
service_purge() {
    if confirm_operation "WARNING: This will DELETE ALL DATA and volumes!" "N"; then
        echo -e "${RED}Purging all services and data...${NC}"
        $DOCKER_COMPOSE down -v
        output_result "success" "All services and data purged"
    else
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"cancelled","message":"User cancelled operation"}'
        else
            echo "Cancelled"
        fi
    fi
}

# Export functions
export -f handle_service_command
export -f ensure_services_ready
export -f service_up
export -f service_down
export -f service_restart
export -f service_status
export -f service_logs
export -f service_shell
export -f service_list
export -f service_purge