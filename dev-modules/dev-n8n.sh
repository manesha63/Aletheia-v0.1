#!/bin/bash

# ============================================================================
# Dev CLI n8n Module - Enhanced with Node Management
# ============================================================================
# This module contains all n8n-related commands including workflow and node management
# Integrates features from PR #130 while maintaining modular architecture

# Helper function to detect package manager for a node
detect_package_manager() {
    local node_dir="$1"
    if [ -f "$node_dir/pnpm-lock.yaml" ]; then
        echo "pnpm"
    elif [ -f "$node_dir/yarn.lock" ]; then
        echo "yarn"
    else
        echo "npm"
    fi
}

# Helper function to build a single node
build_node() {
    local node_dir="$1"
    local node_name=$(basename "$node_dir")
    
    echo -e "${CYAN}Building $node_name...${NC}"
    
    if [ ! -f "$node_dir/package.json" ]; then
        echo -e "${RED}  ✗ No package.json found${NC}"
        return 1
    fi
    
    # Detect package manager
    local pkg_manager=$(detect_package_manager "$node_dir")
    
    # Install dependencies
    echo "  Installing dependencies with $pkg_manager..."
    cd "$node_dir"
    
    case "$pkg_manager" in
        pnpm)
            pnpm install --frozen-lockfile || {
                echo -e "${RED}  ✗ Failed to install dependencies${NC}"
                return 1
            }
            ;;
        yarn)
            yarn install --frozen-lockfile || {
                echo -e "${RED}  ✗ Failed to install dependencies${NC}"
                return 1
            }
            ;;
        npm)
            npm ci || npm install || {
                echo -e "${RED}  ✗ Failed to install dependencies${NC}"
                return 1
            }
            ;;
    esac
    
    # Build the node
    echo "  Building..."
    npm run build || {
        echo -e "${RED}  ✗ Build failed${NC}"
        return 1
    }
    
    echo -e "${GREEN}  ✓ $node_name built successfully${NC}"
    return 0
}

# Main n8n command handler
handle_n8n_command() {
    local cmd="$1"
    shift
    
    case "$cmd" in
        setup)
            echo -e "${BLUE}Running n8n auto-setup...${NC}"
            if ! check_service_running "n8n"; then
                exit $EXIT_SERVICE_UNAVAILABLE
            fi
            
            # Run auto-setup
            $DOCKER_COMPOSE exec -T n8n sh /usr/local/bin/auto-setup
            
            echo ""
            echo -e "${GREEN}Setup complete!${NC}"
            echo "Access n8n at: http://localhost:${N8N_PORT:-8100}"
            echo "Login: admin@aletheia.local / admin123"
            ;;
            
        workflows)
            case "$1" in
                list)
                    echo -e "${BLUE}Listing n8n workflows...${NC}"
                    if ! check_service_running "n8n"; then
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    # Execute n8n CLI inside container to list workflows
                    $DOCKER_COMPOSE exec -T n8n n8n list:workflow 2>/dev/null || {
                        echo -e "${RED}Failed to list workflows. n8n may still be starting up.${NC}"
                        exit 1
                    }
                    ;;
                    
                import)
                    echo -e "${BLUE}Importing workflows to n8n...${NC}"
                    if ! check_service_running "n8n"; then
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    
                    # Check if workflow_json directory exists
                    if [ ! -d "workflow_json" ]; then
                        echo -e "${RED}workflow_json directory not found${NC}"
                        exit 1
                    fi
                    
                    # Count workflow files
                    workflow_count=$(find workflow_json -name "*.json" -type f 2>/dev/null | wc -l)
                    if [ $workflow_count -eq 0 ]; then
                        echo -e "${YELLOW}No workflow files found in workflow_json/${NC}"
                        exit 0
                    fi
                    
                    echo "Found $workflow_count workflow file(s) to import"
                    
                    # Copy workflows to container and import
                    for workflow_file in workflow_json/*.json; do
                        if [ -f "$workflow_file" ]; then
                            basename=$(basename "$workflow_file")
                            echo -n "  • Importing $basename... "
                            
                            # Copy file to container
                            docker cp "$workflow_file" "$(docker-compose ps -q n8n):/tmp/$basename"
                            
                            # Import using n8n CLI
                            if $DOCKER_COMPOSE exec -T n8n n8n import:workflow --input="/tmp/$basename" 2>/dev/null; then
                                echo -e "${GREEN}✓${NC}"
                            else
                                echo -e "${RED}✗${NC}"
                            fi
                            
                            # Clean up temp file
                            $DOCKER_COMPOSE exec -T n8n rm -f "/tmp/$basename"
                        fi
                    done
                    
                    echo -e "${GREEN}Workflow import complete${NC}"
                    ;;
                    
                export)
                    echo -e "${BLUE}Exporting n8n workflows...${NC}"
                    if ! check_service_running "n8n"; then
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    
                    # Create export directory
                    export_dir="workflow_export_$(date +%Y%m%d_%H%M%S)"
                    mkdir -p "$export_dir"
                    
                    echo "Exporting workflows to $export_dir/"
                    
                    # Get list of workflows and export each
                    workflow_list=$($DOCKER_COMPOSE exec -T n8n n8n list:workflow 2>/dev/null | grep -v "User settings" | grep -v "Error tracking" | grep "|")
                    
                    if [ -z "$workflow_list" ]; then
                        echo -e "${YELLOW}No workflows found to export${NC}"
                        rmdir "$export_dir"
                        exit 0
                    fi
                    
                    echo "$workflow_list" | while IFS='|' read -r workflow_id workflow_name rest; do
                        workflow_id=$(echo "$workflow_id" | tr -d ' ')
                        workflow_name=$(echo "$workflow_name" | tr -d ' ' | tr '/' '_')
                        
                        if [ -z "$workflow_id" ] || [ "$workflow_id" = "ID" ]; then
                            continue
                        fi
                        
                        echo -n "  • Exporting workflow $workflow_id ($workflow_name)... "
                        
                        # Export workflow to container temp file
                        if $DOCKER_COMPOSE exec -T n8n n8n export:workflow --id="$workflow_id" --output="/tmp/workflow_$workflow_id.json" 2>/dev/null; then
                            # Copy from container to host
                            docker cp "$($DOCKER_COMPOSE ps -q n8n):/tmp/workflow_$workflow_id.json" "$export_dir/${workflow_name}.json" 2>/dev/null
                            $DOCKER_COMPOSE exec -T n8n rm -f "/tmp/workflow_$workflow_id.json" 2>/dev/null
                            echo -e "${GREEN}✓${NC}"
                        else
                            echo -e "${RED}✗${NC}"
                        fi
                    done
                    
                    echo -e "${GREEN}Workflows exported to $export_dir/${NC}"
                    ;;
                    
                reset)
                    echo -e "${YELLOW}This will clear all n8n workflows and reimport from workflow_json/${NC}"
                    read -p "Are you sure? (y/N) " -n 1 -r
                    echo
                    if [[ $REPLY =~ ^[Yy]$ ]]; then
                        echo -e "${BLUE}Resetting n8n workflows...${NC}"
                        
                        # Stop n8n
                        echo "Stopping n8n..."
                        $DOCKER_COMPOSE stop n8n
                        
                        # Clear the database volume
                        echo "Clearing n8n database..."
                        docker volume rm "${PROJECT_NAME}_n8n_data" 2>/dev/null || true
                        
                        # Start n8n with force reimport
                        echo "Starting n8n with force reimport..."
                        FORCE_REIMPORT=true $DOCKER_COMPOSE up -d n8n
                        
                        echo -e "${GREEN}Workflow reset initiated. Check logs with: ./dev logs n8n${NC}"
                    else
                        echo "Cancelled"
                    fi
                    ;;
                    
                activate)
                    echo -e "${BLUE}Activating all n8n workflows...${NC}"
                    if ! check_service_running "n8n"; then
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    
                    if $DOCKER_COMPOSE exec -T n8n n8n update:workflow --all --active=true 2>/dev/null; then
                        echo -e "${GREEN}All workflows activated${NC}"
                    else
                        echo -e "${RED}Failed to activate workflows${NC}"
                        exit 1
                    fi
                    ;;
                    
                deactivate)
                    if [ -z "$2" ]; then
                        echo -e "${BLUE}Deactivating all n8n workflows...${NC}"
                        if ! check_service_running "n8n"; then
                            exit $EXIT_SERVICE_UNAVAILABLE
                        fi
                        
                        if $DOCKER_COMPOSE exec -T n8n n8n update:workflow --all --active=false 2>/dev/null; then
                            echo -e "${GREEN}All workflows deactivated${NC}"
                        else
                            echo -e "${RED}Failed to deactivate workflows${NC}"
                            exit 1
                        fi
                    else
                        echo -e "${BLUE}Deactivating workflow $2...${NC}"
                        if $DOCKER_COMPOSE exec -T n8n n8n update:workflow --id="$2" --active=false 2>/dev/null; then
                            echo -e "${GREEN}Workflow $2 deactivated${NC}"
                        else
                            echo -e "${RED}Failed to deactivate workflow $2${NC}"
                            exit 1
                        fi
                    fi
                    ;;
                    
                execute)
                    if [ -z "$2" ]; then
                        echo "Usage: ./dev n8n workflows execute <workflow-id>"
                        exit 1
                    fi
                    echo -e "${BLUE}Executing workflow $2...${NC}"
                    if ! check_service_running "n8n"; then
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    
                    if $DOCKER_COMPOSE exec -T n8n n8n execute --id="$2" 2>/dev/null; then
                        echo -e "${GREEN}Workflow executed successfully${NC}"
                    else
                        echo -e "${RED}Failed to execute workflow${NC}"
                        exit 1
                    fi
                    ;;
                    
                status)
                    echo -e "${BLUE}Checking n8n workflow status...${NC}"
                    if ! check_service_running "n8n"; then
                        echo -e "${RED}n8n is not running${NC}"
                        exit $EXIT_SERVICE_UNAVAILABLE
                    fi
                    
                    # List all workflows with status
                    echo ""
                    echo -e "${CYAN}All Workflows:${NC}"
                    $DOCKER_COMPOSE exec -T n8n n8n list:workflow 2>/dev/null || echo "None"
                    ;;
                    
                *)
                    echo "Usage: ./dev n8n workflows <command>"
                    echo ""
                    echo "Commands:"
                    echo "  list        - List all workflows"
                    echo "  import      - Import workflows from workflow_json/"
                    echo "  export      - Export all workflows"
                    echo "  reset       - Clear and reimport all workflows"
                    echo "  activate    - Activate all workflows"
                    echo "  deactivate  - Deactivate all (or specific) workflow(s)"
                    echo "  execute     - Execute a specific workflow"
                    echo "  status      - Show workflow status"
                    ;;
            esac
            ;;
            
        nodes)
            case "$1" in
                list)
                    echo -e "${BLUE}═══════════════════════════════════════${NC}"
                    echo -e "${BLUE}  n8n Custom Nodes Inventory${NC}"
                    echo -e "${BLUE}═══════════════════════════════════════${NC}"
                    echo ""
                    
                    total_nodes=0
                    built_nodes=0
                    loaded_nodes=0
                    
                    # Check host filesystem nodes
                    echo -e "${CYAN}Local Custom Nodes:${NC}"
                    for node_dir in n8n/custom-nodes/n8n-nodes-*; do
                        if [ -d "$node_dir" ]; then
                            node_name=$(basename "$node_dir")
                            total_nodes=$((total_nodes + 1))
                            
                            if [ -f "$node_dir/package.json" ]; then
                                version=$(grep '"version"' "$node_dir/package.json" | head -1 | cut -d'"' -f4)
                                description=$(grep '"description"' "$node_dir/package.json" | head -1 | cut -d'"' -f4)
                                
                                echo "  • $node_name (v$version)"
                                [ -n "$description" ] && echo "    Description: $description"
                                
                                # Check build status
                                if [ -d "$node_dir/dist" ]; then
                                    echo -e "    Build Status: ${GREEN}Built ✓${NC}"
                                    built_nodes=$((built_nodes + 1))
                                    
                                    # Check if TypeScript or JavaScript based
                                    if [ -f "$node_dir/tsconfig.json" ]; then
                                        echo "    Type: TypeScript"
                                    else
                                        echo "    Type: JavaScript"
                                    fi
                                    
                                    # Check package manager
                                    pkg_manager=$(detect_package_manager "$node_dir")
                                    echo "    Package Manager: $pkg_manager"
                                else
                                    echo -e "    Build Status: ${RED}Not built ✗${NC}"
                                    echo -e "    ${YELLOW}Action: Run './dev n8n nodes build $node_name'${NC}"
                                fi
                            fi
                            echo ""
                        fi
                    done
                    
                    # Check container-loaded nodes if n8n is running
                    if check_service_running "n8n" 2>/dev/null; then
                        echo -e "${CYAN}Container Status:${NC}"
                        if $DOCKER_COMPOSE exec -T n8n test -d /data/.n8n/custom 2>/dev/null; then
                            loaded_count=$($DOCKER_COMPOSE exec -T n8n ls -la /data/.n8n/custom/ 2>/dev/null | grep "^d" | wc -l)
                            loaded_nodes=$loaded_count
                            echo -e "  ${GREEN}✓${NC} Custom nodes directory exists"
                            echo "  Loaded nodes: $loaded_count"
                        else
                            echo -e "  ${RED}✗${NC} Custom nodes directory not found in container"
                        fi
                    else
                        echo -e "${YELLOW}Note: n8n is not running. Start with './dev up n8n' to check loaded nodes.${NC}"
                    fi
                    
                    # Summary
                    echo ""
                    echo -e "${CYAN}Summary:${NC}"
                    echo "  Total nodes found: $total_nodes"
                    echo "  Built nodes: $built_nodes"
                    if check_service_running "n8n" 2>/dev/null; then
                        echo "  Loaded in container: $loaded_nodes"
                    fi
                    
                    if [ $built_nodes -lt $total_nodes ]; then
                        echo ""
                        echo -e "${YELLOW}Tip: Run './dev n8n nodes build' to build all nodes${NC}"
                    fi
                    ;;
                    
                add)
                    if [ -z "$2" ]; then
                        echo "Usage: ./dev n8n nodes add <path-to-node>"
                        echo ""
                        echo "Add and build a custom n8n node"
                        echo ""
                        echo "Example:"
                        echo "  ./dev n8n nodes add ./my-custom-node"
                        exit 1
                    fi
                    
                    local node_path="$2"
                    if [ ! -d "$node_path" ]; then
                        echo -e "${RED}Error: Directory $node_path does not exist${NC}"
                        exit 1
                    fi
                    
                    if [ ! -f "$node_path/package.json" ]; then
                        echo -e "${RED}Error: No package.json found in $node_path${NC}"
                        exit 1
                    fi
                    
                    # Get node name from package.json
                    node_name=$(grep '"name"' "$node_path/package.json" | head -1 | cut -d'"' -f4)
                    
                    echo -e "${BLUE}Adding custom node: $node_name${NC}"
                    
                    # Copy to custom-nodes directory
                    target_dir="n8n/custom-nodes/$node_name"
                    if [ -d "$target_dir" ]; then
                        echo -e "${YELLOW}Warning: Node already exists at $target_dir${NC}"
                        read -p "Overwrite? (y/N) " -n 1 -r
                        echo
                        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                            echo "Cancelled"
                            exit 0
                        fi
                        rm -rf "$target_dir"
                    fi
                    
                    cp -r "$node_path" "$target_dir"
                    echo -e "${GREEN}✓${NC} Node copied to $target_dir"
                    
                    # Build the node
                    build_node "$target_dir"
                    
                    # Rebuild Docker image
                    echo ""
                    echo -e "${BLUE}Rebuilding n8n Docker image...${NC}"
                    $DOCKER_COMPOSE build n8n
                    
                    echo ""
                    echo -e "${GREEN}Node added successfully!${NC}"
                    echo "Restart n8n to load the new node: ./dev restart n8n"
                    ;;
                    
                build)
                    echo -e "${BLUE}Building n8n custom nodes...${NC}"
                    echo ""
                    
                    if [ -n "$2" ]; then
                        # Build specific node
                        node_dir="n8n/custom-nodes/$2"
                        if [ ! -d "$node_dir" ]; then
                            # Try with n8n-nodes- prefix
                            node_dir="n8n/custom-nodes/n8n-nodes-$2"
                            if [ ! -d "$node_dir" ]; then
                                echo -e "${RED}Error: Node $2 not found${NC}"
                                exit 1
                            fi
                        fi
                        build_node "$node_dir"
                    else
                        # Build all nodes
                        success_count=0
                        fail_count=0
                        
                        for node_dir in n8n/custom-nodes/n8n-nodes-*; do
                            if [ -d "$node_dir" ]; then
                                if build_node "$node_dir"; then
                                    success_count=$((success_count + 1))
                                else
                                    fail_count=$((fail_count + 1))
                                fi
                                echo ""
                            fi
                        done
                        
                        # Summary
                        echo -e "${CYAN}Build Summary:${NC}"
                        echo -e "  ${GREEN}✓${NC} Successful: $success_count"
                        if [ $fail_count -gt 0 ]; then
                            echo -e "  ${RED}✗${NC} Failed: $fail_count"
                        fi
                    fi
                    ;;
                    
                verify)
                    echo -e "${BLUE}═══════════════════════════════════════${NC}"
                    echo -e "${BLUE}  n8n Custom Nodes Verification${NC}"
                    echo -e "${BLUE}═══════════════════════════════════════${NC}"
                    echo ""
                    
                    all_good=true
                    
                    # Check each node
                    for node_dir in n8n/custom-nodes/n8n-nodes-*; do
                        if [ -d "$node_dir" ]; then
                            node_name=$(basename "$node_dir")
                            echo -n "  • $node_name: "
                            
                            issues=""
                            
                            # Check package.json
                            if [ ! -f "$node_dir/package.json" ]; then
                                issues="${issues}no package.json; "
                                all_good=false
                            fi
                            
                            # Check dist directory
                            if [ ! -d "$node_dir/dist" ]; then
                                issues="${issues}not built; "
                                all_good=false
                            fi
                            
                            # Check node_modules
                            if [ ! -d "$node_dir/node_modules" ]; then
                                issues="${issues}no dependencies; "
                                all_good=false
                            fi
                            
                            if [ -z "$issues" ]; then
                                echo -e "${GREEN}✓ OK${NC}"
                            else
                                echo -e "${RED}✗ Issues: ${issues}${NC}"
                            fi
                        fi
                    done
                    
                    echo ""
                    if [ "$all_good" = true ]; then
                        echo -e "${GREEN}All nodes verified successfully!${NC}"
                    else
                        echo -e "${YELLOW}Some nodes have issues. Run './dev n8n nodes build' to fix.${NC}"
                    fi
                    
                    # Check container status
                    if check_service_running "n8n" 2>/dev/null; then
                        echo ""
                        echo -e "${CYAN}Container Integration:${NC}"
                        if $DOCKER_COMPOSE exec -T n8n test -d /data/.n8n/custom 2>/dev/null; then
                            echo -e "  ${GREEN}✓${NC} Custom nodes directory exists in container"
                            
                            # Count loaded nodes
                            loaded=$($DOCKER_COMPOSE exec -T n8n ls /data/.n8n/custom/ 2>/dev/null | wc -l)
                            echo "  Nodes loaded in container: $loaded"
                        else
                            echo -e "  ${RED}✗${NC} Custom nodes directory not found in container"
                            echo -e "  ${YELLOW}Action: Rebuild container with './dev rebuild n8n'${NC}"
                        fi
                    fi
                    ;;
                    
                remove)
                    if [ -z "$2" ]; then
                        echo "Usage: ./dev n8n nodes remove <node-name>"
                        echo ""
                        echo "Remove a custom node from n8n"
                        echo ""
                        echo "Example:"
                        echo "  ./dev n8n nodes remove n8n-nodes-example"
                        exit 1
                    fi
                    
                    node_name="$2"
                    node_dir="n8n/custom-nodes/$node_name"
                    
                    if [ ! -d "$node_dir" ]; then
                        # Try with n8n-nodes- prefix
                        node_dir="n8n/custom-nodes/n8n-nodes-$node_name"
                        if [ ! -d "$node_dir" ]; then
                            echo -e "${RED}Error: Node $node_name not found${NC}"
                            exit 1
                        fi
                    fi
                    
                    echo -e "${YELLOW}This will remove the node: $(basename $node_dir)${NC}"
                    read -p "Are you sure? (y/N) " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Cancelled"
                        exit 0
                    fi
                    
                    rm -rf "$node_dir"
                    echo -e "${GREEN}✓${NC} Node removed"
                    
                    echo ""
                    echo -e "${YELLOW}Note: Rebuild n8n to update the container:${NC}"
                    echo "  ./dev rebuild n8n"
                    ;;
                    
                rebuild)
                    echo -e "${BLUE}Rebuilding all custom nodes...${NC}"
                    echo ""
                    
                    # Clean and rebuild all nodes
                    echo -e "${CYAN}1. Cleaning old builds...${NC}"
                    for node_dir in n8n/custom-nodes/n8n-nodes-*; do
                        if [ -d "$node_dir/dist" ]; then
                            rm -rf "$node_dir/dist"
                            echo "  Cleaned $(basename $node_dir)"
                        fi
                    done
                    
                    echo ""
                    echo -e "${CYAN}2. Rebuilding nodes...${NC}"
                    success_count=0
                    fail_count=0
                    
                    for node_dir in n8n/custom-nodes/n8n-nodes-*; do
                        if [ -d "$node_dir" ]; then
                            if build_node "$node_dir"; then
                                success_count=$((success_count + 1))
                            else
                                fail_count=$((fail_count + 1))
                            fi
                            echo ""
                        fi
                    done
                    
                    # Summary
                    echo -e "${CYAN}Rebuild Summary:${NC}"
                    echo -e "  ${GREEN}✓${NC} Successful: $success_count"
                    if [ $fail_count -gt 0 ]; then
                        echo -e "  ${RED}✗${NC} Failed: $fail_count"
                    fi
                    
                    echo ""
                    echo -e "${CYAN}3. Rebuilding Docker image...${NC}"
                    $DOCKER_COMPOSE build n8n
                    
                    echo ""
                    echo -e "${GREEN}Rebuild complete!${NC}"
                    echo "Restart n8n to load the updated nodes: ./dev restart n8n"
                    ;;
                    
                *)
                    echo "Usage: ./dev n8n nodes <command>"
                    echo ""
                    echo "Commands:"
                    echo "  list     - List all custom nodes and their status"
                    echo "  add      - Add a new custom node"
                    echo "  build    - Build custom node(s)"
                    echo "  verify   - Verify node configuration and build status"
                    echo "  remove   - Remove a custom node"
                    echo "  rebuild  - Clean and rebuild all nodes"
                    ;;
            esac
            ;;
            
        config)
            case "$1" in
                show)
                    echo -e "${BLUE}n8n Configuration:${NC}"
                    echo ""
                    if [ -f n8n_data/config ]; then
                        echo -e "${CYAN}Config file contents:${NC}"
                        cat n8n_data/config
                    else
                        echo -e "${YELLOW}No config file found${NC}"
                    fi
                    echo ""
                    echo -e "${CYAN}Environment variables:${NC}"
                    echo "  N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:0:20}..."
                    echo "  N8N_PORT: ${N8N_PORT:-8100}"
                    echo "  N8N_HOST: ${SERVICE_HOST:-0.0.0.0}"
                    ;;
                    
                reset)
                    echo -e "${YELLOW}This will reset n8n encryption configuration${NC}"
                    read -p "Are you sure? (y/N) " -n 1 -r
                    echo
                    if [[ $REPLY =~ ^[Yy]$ ]]; then
                        # Stop n8n
                        echo "Stopping n8n..."
                        $DOCKER_COMPOSE stop n8n
                        
                        # Backup and remove config
                        if [ -f n8n_data/config ]; then
                            mv n8n_data/config n8n_data/config.backup.$(date +%s)
                            echo "Config backed up"
                        fi
                        
                        # Start n8n
                        echo "Starting n8n with fresh config..."
                        $DOCKER_COMPOSE up -d n8n
                        
                        echo -e "${GREEN}Config reset complete${NC}"
                    else
                        echo "Cancelled"
                    fi
                    ;;
                    
                *)
                    echo "Usage: ./dev n8n config <command>"
                    echo ""
                    echo "Commands:"
                    echo "  show   - Show current configuration"
                    echo "  reset  - Reset encryption configuration"
                    ;;
            esac
            ;;
            
        logs)
            echo -e "${BLUE}Showing n8n logs...${NC}"
            $DOCKER_COMPOSE logs -f --tail=100 n8n
            ;;
            
        shell)
            echo -e "${BLUE}Opening n8n shell...${NC}"
            $DOCKER_COMPOSE exec n8n /bin/sh
            ;;
            
        *)
            echo "Usage: ./dev n8n <command>"
            echo ""
            echo "Commands:"
            echo "  setup      - Run initial n8n setup"
            echo "  workflows  - Manage n8n workflows"
            echo "  nodes      - Manage custom nodes"
            echo "  config     - Manage n8n configuration"
            echo "  logs       - Show n8n logs"
            echo "  shell      - Open n8n container shell"
            echo ""
            echo "Examples:"
            echo "  ./dev n8n workflows list"
            echo "  ./dev n8n nodes build"
            echo "  ./dev n8n config show"
            ;;
    esac
}