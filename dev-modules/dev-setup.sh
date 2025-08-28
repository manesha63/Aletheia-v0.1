#!/bin/bash

# ============================================================================
# Dev CLI Setup Module
# ============================================================================
# This module handles initial setup and configuration

# Handle setup command
handle_setup_command() {
    utils_setup "$@"
}

# Setup wizard for initial configuration
utils_setup() {
    local FORCE=false
    local NON_INTERACTIVE=false
    
    # Parse arguments
    for arg in "$@"; do
        case "$arg" in
            --force|-f)
                FORCE=true
                ;;
            --non-interactive|-n)
                NON_INTERACTIVE=true
                ;;
            --help|-h)
                echo "Usage: ./dev setup [options]"
                echo ""
                echo "Options:"
                echo "  --non-interactive, -n  Run without prompts (backup existing .env)"
                echo "  --force, -f           Overwrite .env without backup"
                echo "  --help, -h            Show this help message"
                return $EXIT_SUCCESS
                ;;
        esac
    done
    
    if [ "$OUTPUT_FORMAT" != "json" ]; then
        echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
        echo -e "${BLUE}║       Aletheia Setup Wizard            ║${NC}"
        echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
        echo ""
    fi
    
    if [ -f .env ]; then
        if [ "$FORCE" = true ]; then
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo '{"status":"info","message":"Overwriting existing .env file"}'
            else
                echo -e "${YELLOW}⚠ Overwriting existing .env file (--force)${NC}"
            fi
        elif [ "$NON_INTERACTIVE" = true ]; then
            timestamp=$(date +%Y%m%d_%H%M%S)
            cp .env ".env.backup_${timestamp}"
            if [ "$OUTPUT_FORMAT" = "json" ]; then
                echo "{\"status\":\"success\",\"message\":\"Backed up existing .env\",\"backup_file\":\".env.backup_${timestamp}\"}"
            else
                echo -e "${GREEN}✓ Backed up existing .env to .env.backup_${timestamp}${NC}"
            fi
        else
            echo -e "${YELLOW}⚠ .env file already exists${NC}"
            echo -n "Backup and create new? (y/N): "
            read -r response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                echo "Setup cancelled"
                return $EXIT_USER_CANCELLED
            fi
            
            timestamp=$(date +%Y%m%d_%H%M%S)
            cp .env ".env.backup_${timestamp}"
            echo -e "${GREEN}✓ Backed up to .env.backup_${timestamp}${NC}"
        fi
    fi
    
    # Create .env with secure passwords
    cat > .env << EOF
# Aletheia Configuration - Generated $(date)
COMPOSE_PROJECT_NAME=aletheia_development
ENVIRONMENT=development

# Database
DB_USER=aletheia
DB_PASSWORD=$(generate_password 32)
DB_NAME=aletheia
DB_HOST=db
DB_PORT=5432

# Ports
WEB_PORT=8080
N8N_PORT=8100
AI_PORTAL_PORT=8102
COURT_PROCESSOR_PORT=8104
POSTGRES_PORT=8200
REDIS_PORT=8201
ELASTICSEARCH_PORT=9200
ELASTICSEARCH_CLUSTER_PORT=9300
HAYSTACK_PORT=8000
UNSTRUCTURED_PORT=8880

# Security
N8N_ENCRYPTION_KEY=$(generate_password 32)
NEXTAUTH_SECRET=$(generate_password 64)
N8N_WEBHOOK_ID=c188c31c-1c45-4118-9ece-5b6057ab5177

# Optional - N8N API Credentials (leave empty if not using API)
N8N_API_KEY=
N8N_API_SECRET=

# Optional - AI Service Keys
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Optional - Web Configuration
COURT_API_BASE_URL=
NEXT_PUBLIC_WEB_URL=http://localhost:8080
NEXT_PUBLIC_AI_PORTAL_URL=http://localhost:8102
NEXT_PUBLIC_N8N_URL=http://localhost:8100
NEXT_PUBLIC_COURT_API_URL=http://localhost:8104
WEB_HOST=0.0.0.0
REVERSE_PROXY_PORT=

# Optional - SMTP Configuration
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
SMTP_FROM=

# Optional - External Services
COURTLISTENER_API_TOKEN=
PACER_USERNAME=
PACER_PASSWORD=

# Optional - Feature Flags
NEXT_PUBLIC_ENABLE_DOCUMENT_SELECTION=true
NEXT_PUBLIC_MAX_DOCUMENT_SELECTIONS=10
FIELD_ENCRYPTION_KEY=
EOF
    
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{"status":"success","message":"Generated .env with secure credentials"}'
    else
        echo -e "${GREEN}✓ Generated .env with secure credentials${NC}"
        echo ""
        
        # Notify about court data restoration
        if [ -f court-processor/data/court_documents_backup.sql.gz ]; then
            echo -e "${CYAN}Court processor data backup found (485 documents, ~9.5MB)${NC}"
            echo -e "${GREEN}✓ Will be automatically restored when services start${NC}"
        fi
        
        # Notify about n8n auto-setup
        echo ""
        echo -e "${CYAN}n8n Automation:${NC}"
        echo -e "${GREEN}✓ Owner account will be created automatically${NC}"
        echo -e "${GREEN}✓ All workflows will be activated on startup${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Run './dev up' to start services"
        echo "  2. Access n8n at http://localhost:8100"
        echo "  3. Login with: admin@aletheia.local / admin123"
    fi
}

# Export functions
export -f handle_setup_command
export -f utils_setup