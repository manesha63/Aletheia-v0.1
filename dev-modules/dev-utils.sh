#!/bin/bash

# ============================================================================
# Dev CLI Utility Module
# ============================================================================
# This module contains utility commands for setup, maintenance, and diagnostics

# Handle utility commands
handle_utils_command() {
    local cmd="$1"
    shift
    
    case "$cmd" in
        validate)
            utils_validate "$@"
            ;;
        backup)
            utils_backup "$@"
            ;;
        cleanup)
            utils_cleanup "$@"
            ;;
        reload-nginx)
            utils_reload_nginx "$@"
            ;;
        seed-users)
            utils_seed_users "$@"
            ;;
        verify-frontend)
            utils_verify_frontend "$@"
            ;;
        *)
            # Not a utils command
            return 1
            ;;
    esac
}

# Validate system configuration
utils_validate() {
    # Parse arguments
    NON_INTERACTIVE=false
    FORCE=false
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Comprehensive System Validation"
    fi
    
    issues=0
    warnings=0
    
    # Docker checks
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}1. Docker Environment:${NC}"
    fi
    
    if command -v docker &> /dev/null; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Docker installed"
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} Docker not installed"
        fi
        issues=$((issues + 1))
    fi
    
    if docker info &> /dev/null; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Docker daemon running"
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} Docker daemon not running"
        fi
        issues=$((issues + 1))
    fi
    
    if [ -n "$DOCKER_COMPOSE" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} docker-compose installed"
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} docker-compose not installed"
        fi
        issues=$((issues + 1))
    fi
    
    # File checks
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}2. Configuration Files:${NC}"
    fi
    
    if [ -f .env ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} .env exists"
        fi
        source .env
        # Check for common weak passwords
        if [[ "$DB_PASSWORD" =~ ^(password|123456|admin|default|aletheia123|postgres)$ ]]; then
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${YELLOW}⚠${NC}  DB_PASSWORD appears to be a weak/default password (security risk)"
            fi
            warnings=$((warnings + 1))
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${RED}✗${NC} .env missing"
        fi
        issues=$((issues + 1))
    fi
    
    if [ -f "docker-compose.yml" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} docker-compose.yml exists"
        fi
        # Validate docker-compose syntax
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
    
    # Port availability
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}3. Port Availability:${NC}"
    fi
    
    ports_to_check="${WEB_PORT:-8080} ${N8N_PORT:-8100} ${AI_PORTAL_PORT:-8102} ${COURT_PROCESSOR_PORT:-8104} ${POSTGRES_PORT:-8200} ${REDIS_PORT:-8201}"
    port_issues=0
    for port in $ports_to_check; do
        if lsof -i :$port > /dev/null 2>&1; then
            service_name=$(docker ps --format "table {{.Names}}\t{{.Ports}}" | grep $port | awk '{print $1}' | head -1)
            if [ -n "$service_name" ]; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓${NC} Port $port in use by $service_name (expected)"
                fi
            else
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${YELLOW}⚠${NC}  Port $port in use by non-Docker process"
                fi
                port_issues=$((port_issues + 1))
            fi
        else
            if [ "$OUTPUT_FORMAT" != "json" ]; then
                echo -e "${GREEN}✓${NC} Port $port available"
            fi
        fi
    done
    
    if [ $port_issues -gt 0 ]; then
        warnings=$((warnings + port_issues))
    fi
    
    # Service health
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo ""
        echo -e "${CYAN}4. Service Health:${NC}"
    fi
    
    if $DOCKER_COMPOSE ps 2>/dev/null | grep -q "Up"; then
        healthy=$(docker ps --filter "health=healthy" --format "{{.Names}}" | wc -l | tr -d ' ')
        unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" | wc -l | tr -d ' ')
        total=$(docker ps --format "{{.Names}}" | wc -l | tr -d ' ')
        
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} $total services running"
            if [ "$healthy" -gt 0 ]; then
                echo -e "${GREEN}✓${NC} $healthy services healthy"
            fi
            if [ "$unhealthy" -gt 0 ]; then
                echo -e "${YELLOW}⚠${NC}  $unhealthy services unhealthy"
            fi
        fi
        
        if [ "$unhealthy" -gt 0 ]; then
            warnings=$((warnings + unhealthy))
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${YELLOW}⚠${NC}  No services running"
        fi
    fi
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"issues\":$issues,\"warnings\":$warnings,\"healthy\":${healthy:-0},\"unhealthy\":${unhealthy:-0},\"total\":${total:-0}}"
    else
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if [ $issues -eq 0 ] && [ $warnings -eq 0 ]; then
            echo -e "${GREEN}✓ Validation passed${NC}"
        elif [ $issues -eq 0 ]; then
            echo -e "${YELLOW}⚠ Validation passed with $warnings warning(s)${NC}"
        else
            echo -e "${RED}✗ Validation failed: $issues issue(s), $warnings warning(s)${NC}"
        fi
    fi
    
    [ $issues -eq 0 ] && return $EXIT_SUCCESS || return $EXIT_CONFIG_ERROR
}

# Create backup
utils_backup() {
    check_requirements
    
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_dir="backups"
    mkdir -p "$backup_dir"
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${BLUE}Creating backup...${NC}"
    fi
    
    # Backup database
    if $DOCKER_COMPOSE exec -T db pg_dump -U "${DB_USER:-aletheia}" "${DB_NAME:-aletheia}" > "$backup_dir/db_backup_${timestamp}.sql" 2>/dev/null; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Database backed up to $backup_dir/db_backup_${timestamp}.sql"
        fi
    else
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${YELLOW}⚠${NC} Database backup skipped (not running?)"
        fi
    fi
    
    # Backup .env
    if [ -f .env ]; then
        cp .env "$backup_dir/.env.backup_${timestamp}"
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Configuration backed up"
        fi
    fi
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"status\":\"success\",\"timestamp\":\"$timestamp\",\"backup_dir\":\"$backup_dir\"}"
    else
        echo ""
        echo -e "${GREEN}Backup complete!${NC}"
    fi
}

# Archive old files
utils_cleanup() {
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Archiving Old Files"
    fi
    
    # Create archive directories
    mkdir -p .archive/{nginx,docker,tests,misc}
    
    total_moved=0
    
    # Archive nginx configs
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}Archiving old nginx configs...${NC}"
    fi
    moved=0
    for file in nginx/conf.d/*.bak nginx/conf.d/*.disabled nginx/conf.d/*.backup; do
        if [ -f "$file" ]; then
            mv "$file" .archive/nginx/ 2>/dev/null && moved=$((moved + 1))
        fi
    done
    total_moved=$((total_moved + moved))
    if [ "$OUTPUT_FORMAT" != "json" ] && [ $moved -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Archived $moved nginx config files"
    fi
    
    # Archive old docker-compose files
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}Archiving unused docker-compose files...${NC}"
    fi
    moved=0
    for file in docker-compose.{unified,staging,swarm,env}.yml; do
        if [ -f "$file" ]; then
            mv "$file" .archive/docker/ 2>/dev/null && moved=$((moved + 1))
        fi
    done
    total_moved=$((total_moved + moved))
    if [ "$OUTPUT_FORMAT" != "json" ] && [ $moved -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Archived $moved docker-compose files"
    fi
    
    # Find and archive .bak files
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${CYAN}Finding backup files...${NC}"
    fi
    found=$(find . -maxdepth 3 -name "*.bak" -o -name "*.backup*" 2>/dev/null | grep -v .archive | wc -l)
    if [ $found -gt 0 ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${YELLOW}Found $found backup files. Archive them? (y/N): ${NC}"
            read -r response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                find . -maxdepth 3 \( -name "*.bak" -o -name "*.backup*" \) -not -path "./.archive/*" -exec mv {} .archive/misc/ \; 2>/dev/null
                echo -e "${GREEN}✓${NC} Archived backup files"
                total_moved=$((total_moved + found))
            fi
        else
            # In JSON mode, archive automatically
            find . -maxdepth 3 \( -name "*.bak" -o -name "*.backup*" \) -not -path "./.archive/*" -exec mv {} .archive/misc/ \; 2>/dev/null
            total_moved=$((total_moved + found))
        fi
    fi
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"status\":\"success\",\"files_archived\":$total_moved}"
    else
        # Report on test directories
        echo ""
        echo -e "${CYAN}Test directories found:${NC}"
        [ -d "pacer-test-implementation" ] && echo "  • pacer-test-implementation/ ($(find pacer-test-implementation -type f | wc -l) files)"
        [ -d "test" ] && echo "  • test/ ($(find test -type f | wc -l) files)"
        [ -d "test-data" ] && echo "  • test-data/ ($(find test-data -type f | wc -l) files)"
        [ -d "tests" ] && echo "  • tests/ ($(find tests -type f | wc -l) files)"
        echo ""
        echo -e "${YELLOW}Note: Test directories need manual review before archiving${NC}"
        echo "To consolidate: mv test* tests/ && mv pacer-test-implementation tests/"
        
        echo ""
        echo -e "${GREEN}Cleanup complete!${NC}"
        echo "Archived files are in .archive/"
    fi
}

# Reload nginx configuration
utils_reload_nginx() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${BLUE}Reloading nginx configuration...${NC}"
    fi
    
    if $DOCKER_COMPOSE exec -T web nginx -t 2>/dev/null; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${GREEN}✓${NC} Configuration valid"
        fi
        $DOCKER_COMPOSE exec -T web nginx -s reload 2>/dev/null
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"success","message":"Nginx reloaded"}'
        else
            echo -e "${GREEN}✓${NC} Nginx reloaded"
        fi
    else
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"error","message":"Configuration invalid"}'
        else
            echo -e "${RED}✗${NC} Configuration invalid"
        fi
        return $EXIT_CONFIG_ERROR
    fi
}

# Seed demo users
utils_seed_users() {
    check_requirements
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        print_header "Seeding Lawyer-Chat Demo Users"
    fi
    
    # Check if database is running
    if ! check_db_ready; then
        return $EXIT_SERVICE_UNAVAILABLE
    fi
    
    # Check if User table exists
    USER_TABLE_EXISTS=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" -t -c \
        "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'User');" 2>/dev/null | tr -d ' ')
    
    if [ "$USER_TABLE_EXISTS" = "f" ] || [ "$USER_TABLE_EXISTS" = "false" ]; then
        if [ "$OUTPUT_FORMAT" != "json" ]; then
            echo -e "${BLUE}Creating database schema...${NC}"
        fi
        
        if [ -d "services/lawyer-chat" ]; then
            cd services/lawyer-chat
            # URL-encode the password to handle special characters
            ENCODED_PASSWORD=$(url_encode "${DB_PASSWORD}")
            export DATABASE_URL="postgresql://${DB_USER:-aletheia}:${ENCODED_PASSWORD}@localhost:${POSTGRES_PORT:-8200}/${DB_NAME:-aletheia}"
            
            # Push schema to database
            if npx prisma db push --force-reset --skip-generate &>/dev/null 2>&1; then
                if [ "$OUTPUT_FORMAT" != "json" ]; then
                    echo -e "${GREEN}✓ Database schema created${NC}"
                fi
                
                # Generate Prisma client
                if npx prisma generate &>/dev/null 2>&1; then
                    if [ "$OUTPUT_FORMAT" != "json" ]; then
                        echo -e "${GREEN}✓ Prisma client generated${NC}"
                    fi
                else
                    if [ "$OUTPUT_FORMAT" != "json" ]; then
                        echo -e "${YELLOW}⚠ Failed to generate Prisma client${NC}"
                    fi
                fi
            else
                if [ "$OUTPUT_FORMAT" = "json" ]; then
                    echo '{"status":"error","message":"Failed to create database schema"}'
                else
                    echo -e "${RED}✗ Failed to create database schema${NC}"
                fi
                cd - &>/dev/null
                return $EXIT_RESOURCE_ERROR
            fi
            
            cd - &>/dev/null
        else
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"error","message":"Lawyer-chat service directory not found"}'
            else
                echo -e "${RED}✗ Lawyer-chat service directory not found${NC}"
            fi
            return $EXIT_CONFIG_ERROR
        fi
    fi
    
    # Check if demo users already exist
    USER_COUNT=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" -t -c \
        "SELECT COUNT(*) FROM \"User\" WHERE email IN ('demo@reichmanjorgensen.com', 'admin@reichmanjorgensen.com');" 2>/dev/null | tr -d ' ')
    
    if [ "$USER_COUNT" = "2" ]; then
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"info","message":"Demo users already exist"}'
        else
            echo -e "${YELLOW}Demo users already exist. Reset them? (y/N): ${NC}"
            read -r response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                echo "Seeding cancelled"
                return $EXIT_USER_CANCELLED
            fi
            
            echo -e "${BLUE}Removing existing demo users...${NC}"
        fi
        $DOCKER_COMPOSE exec -T db psql -U "${DB_USER:-aletheia}" -d "${DB_NAME:-aletheia}" -c \
            "DELETE FROM \"User\" WHERE email IN ('demo@reichmanjorgensen.com', 'admin@reichmanjorgensen.com');" &>/dev/null
    fi
    
    # Seed the users
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${BLUE}Creating demo users...${NC}"
    fi
    
    if [ -d "services/lawyer-chat" ]; then
        cd services/lawyer-chat
        ENCODED_PASSWORD=$(url_encode "${DB_PASSWORD}")
        export DATABASE_URL="postgresql://${DB_USER:-aletheia}:${ENCODED_PASSWORD}@localhost:${POSTGRES_PORT:-8200}/${DB_NAME:-aletheia}"
        
        if [ -f "scripts/seed-users.cjs" ]; then
            if node scripts/seed-users.cjs &>/dev/null 2>&1; then
                if [ "$OUTPUT_FORMAT" = "json" ]; then
                    echo '{"status":"success","message":"Demo users created","users":["demo@reichmanjorgensen.com","admin@reichmanjorgensen.com"]}'
                else
                    echo -e "${GREEN}✓ Demo users created:${NC}"
                    echo "    • demo@reichmanjorgensen.com / demo123"
                    echo "    • admin@reichmanjorgensen.com / admin123"
                fi
            else
                if [ "$OUTPUT_FORMAT" = "json" ]; then
                    echo '{"status":"error","message":"Failed to seed demo users"}'
                else
                    echo -e "${RED}✗ Failed to seed demo users${NC}"
                fi
                cd - &>/dev/null
                return $EXIT_RESOURCE_ERROR
            fi
        elif [ -f "prisma/seed.ts" ]; then
            if npx tsx prisma/seed.ts &>/dev/null 2>&1; then
                if [ "$OUTPUT_FORMAT" = "json" ]; then
                    echo '{"status":"success","message":"Demo users created","users":["demo@reichmanjorgensen.com","admin@reichmanjorgensen.com"]}'
                else
                    echo -e "${GREEN}✓ Demo users created:${NC}"
                    echo "    • demo@reichmanjorgensen.com / demo123"
                    echo "    • admin@reichmanjorgensen.com / admin123"
                fi
            else
                if [ "$OUTPUT_FORMAT" = "json" ]; then
                    echo '{"status":"error","message":"Failed to seed demo users"}'
                else
                    echo -e "${RED}✗ Failed to seed demo users${NC}"
                fi
                cd - &>/dev/null
                return $EXIT_RESOURCE_ERROR
            fi
        fi
        
        cd - &>/dev/null
    fi
}

# Verify frontend
utils_verify_frontend() {
    # Run the verification script
    if [ -f "scripts/verify-lawyer-chat.sh" ]; then
        bash scripts/verify-lawyer-chat.sh
    else
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            echo '{"status":"error","message":"Verification script not found","expected":"scripts/verify-lawyer-chat.sh"}'
        else
            echo -e "${RED}Verification script not found${NC}"
            echo "Expected at: scripts/verify-lawyer-chat.sh"
        fi
        return $EXIT_CONFIG_ERROR
    fi
}

# Export functions
export -f handle_utils_command
export -f utils_validate
export -f utils_backup
export -f utils_cleanup
export -f utils_reload_nginx
export -f utils_seed_users
export -f utils_verify_frontend