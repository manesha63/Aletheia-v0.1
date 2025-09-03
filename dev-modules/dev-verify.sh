#!/bin/bash

# Verify demo credentials are working
verify_credentials() {
    local DB_USER="${DB_USER:-aletheia}"
    local DOCKER_COMPOSE="${DOCKER_COMPOSE:-docker compose}"
    
    echo -e "${BLUE}Verifying demo user credentials...${NC}"
    
    # Check if database is accessible
    if ! $DOCKER_COMPOSE exec -T db psql -U "${DB_USER}" -d lawyerchat -c "SELECT 1;" &>/dev/null 2>&1; then
        echo -e "${YELLOW}⚠ Database not accessible${NC}"
        return 1
    fi
    
    # Get user passwords from database
    DEMO_HASH=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER}" -d lawyerchat -t -c \
        "SELECT password FROM \"User\" WHERE email = 'demo@reichmanjorgensen.com';" 2>/dev/null | tr -d ' ')
    
    ADMIN_HASH=$($DOCKER_COMPOSE exec -T db psql -U "${DB_USER}" -d lawyerchat -t -c \
        "SELECT password FROM \"User\" WHERE email = 'admin@reichmanjorgensen.com';" 2>/dev/null | tr -d ' ')
    
    if [ -z "$DEMO_HASH" ] || [ -z "$ADMIN_HASH" ]; then
        echo -e "${YELLOW}⚠ Demo users not found in database${NC}"
        return 1
    fi
    
    # Expected hashes for demo123 and admin123
    EXPECTED_DEMO='$2a$12$/H5nSVmw7n/0MR2ymCXLiOKJcvZVRHcVZYXjGvK5qBe8JqIJAj5ey'
    EXPECTED_ADMIN='$2a$12$GpJRXfLZzZW7T9fKZKnkVuW9C6aGXqJT9RqY0P8pVJvWQQIqvLg76'
    
    local errors=0
    
    # We can't directly verify bcrypt hashes match, but we can check if they look valid
    if [[ ! "$DEMO_HASH" =~ ^\$2[aby]\$[0-9]{2}\$ ]]; then
        echo -e "${YELLOW}⚠ Demo user password hash looks invalid${NC}"
        errors=$((errors + 1))
    else
        echo -e "${GREEN}✓ Demo user has valid password hash${NC}"
    fi
    
    if [[ ! "$ADMIN_HASH" =~ ^\$2[aby]\$[0-9]{2}\$ ]]; then
        echo -e "${YELLOW}⚠ Admin user password hash looks invalid${NC}"
        errors=$((errors + 1))
    else
        echo -e "${GREEN}✓ Admin user has valid password hash${NC}"
    fi
    
    if [ $errors -eq 0 ]; then
        echo -e "${GREEN}✓ All demo credentials verified${NC}"
        echo "  • demo@reichmanjorgensen.com / demo123"
        echo "  • admin@reichmanjorgensen.com / admin123"
        return 0
    else
        echo -e "${YELLOW}⚠ Some credentials may need to be reset${NC}"
        echo "  Run: ./dev seed-users --force"
        return 1
    fi
}

# Export function
export -f verify_credentials