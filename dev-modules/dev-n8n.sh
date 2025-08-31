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
            
        credentials)
            case "$1" in
                list)
                    echo -e "${BLUE}Listing n8n credentials...${NC}"
                    docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                        "SELECT id, name, type, createdAt FROM credentials_entity;" 2>/dev/null || \
                        echo "No credentials found or database error"
                    ;;
                    
                export)
                    shift
                    output_dir="./n8n/credentials_export_$(date +%Y%m%d_%H%M%S)"
                    
                    if [ "$1" = "--output" ] && [ -n "$2" ]; then
                        output_dir="$2"
                        shift 2
                    fi
                    
                    echo -e "${BLUE}Exporting all n8n credentials...${NC}"
                    mkdir -p "$output_dir"
                    
                    # Export credentials using n8n CLI
                    docker exec aletheia_development-n8n-1 n8n export:credentials \
                        --backup --output="/tmp/export/" 2>/dev/null
                    
                    # Copy from container to host
                    docker cp aletheia_development-n8n-1:/tmp/export/. "$output_dir/"
                    
                    # Clean up container temp files
                    docker exec aletheia_development-n8n-1 rm -rf /tmp/export
                    
                    if [ -d "$output_dir" ] && [ "$(ls -A $output_dir)" ]; then
                        echo -e "${GREEN}✓${NC} Credentials exported to: $output_dir"
                        echo "  Files: $(ls -1 $output_dir | wc -l)"
                    else
                        echo -e "${RED}✗${NC} Export failed or no credentials to export"
                    fi
                    ;;
                    
                import)
                    shift
                    if [ -z "$1" ]; then
                        echo "Usage: ./dev n8n credentials import <file-or-directory>"
                        echo ""
                        echo "Import credentials from JSON file(s)"
                        echo ""
                        echo "Examples:"
                        echo "  ./dev n8n credentials import ./backup.json"
                        echo "  ./dev n8n credentials import ./credentials_export_20240101/"
                        exit 1
                    fi
                    
                    input_path="$1"
                    
                    if [ ! -e "$input_path" ]; then
                        echo -e "${RED}Error: Input path not found: $input_path${NC}"
                        exit 1
                    fi
                    
                    echo -e "${BLUE}Importing n8n credentials...${NC}"
                    
                    # Copy to container
                    docker cp "$input_path" aletheia_development-n8n-1:/tmp/import_creds
                    
                    # Import using n8n CLI
                    if [ -d "$input_path" ]; then
                        # Directory of separate files
                        docker exec aletheia_development-n8n-1 n8n import:credentials \
                            --separate --input="/tmp/import_creds"
                    else
                        # Single file
                        docker exec aletheia_development-n8n-1 n8n import:credentials \
                            --input="/tmp/import_creds"
                    fi
                    
                    # Clean up
                    docker exec aletheia_development-n8n-1 rm -rf /tmp/import_creds
                    
                    echo -e "${GREEN}✓${NC} Import completed"
                    echo ""
                    echo "Verify with: ./dev n8n credentials list"
                    ;;
                    
                backup)
                    backup_dir="./n8n/backups/credentials_$(date +%Y%m%d_%H%M%S)"
                    echo -e "${BLUE}Backing up all n8n credentials...${NC}"
                    
                    mkdir -p "$backup_dir"
                    
                    # Export with decryption for backup (includes sensitive data)
                    echo -e "${YELLOW}Note: Backup will contain decrypted credentials${NC}"
                    read -p "Continue? (y/N) " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Cancelled"
                        exit 0
                    fi
                    
                    # Export decrypted for true backup
                    docker exec aletheia_development-n8n-1 n8n export:credentials \
                        --all --decrypted --pretty --output="/tmp/backup.json"
                    
                    # Copy to host
                    docker cp aletheia_development-n8n-1:/tmp/backup.json "$backup_dir/credentials_decrypted.json"
                    
                    # Also export encrypted version
                    docker exec aletheia_development-n8n-1 n8n export:credentials \
                        --backup --output="/tmp/backup_enc/"
                    
                    docker cp aletheia_development-n8n-1:/tmp/backup_enc/. "$backup_dir/encrypted/"
                    
                    # Clean up
                    docker exec aletheia_development-n8n-1 rm -rf /tmp/backup.json /tmp/backup_enc
                    
                    # Add metadata
                    cat > "$backup_dir/metadata.json" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "n8n_version": "$(docker exec aletheia_development-n8n-1 n8n --version 2>/dev/null || echo 'unknown')",
  "encryption_key_hash": "$(echo -n "$N8N_ENCRYPTION_KEY" | sha256sum | cut -d' ' -f1)",
  "credentials_count": $(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite "SELECT COUNT(*) FROM credentials_entity;" 2>/dev/null || echo 0)
}
EOF
                    
                    echo -e "${GREEN}✓${NC} Backup saved to: $backup_dir"
                    echo "  - credentials_decrypted.json (portable, contains passwords)"
                    echo "  - encrypted/ (requires same encryption key)"
                    echo "  - metadata.json (backup information)"
                    ;;
                    
                restore)
                    shift
                    if [ -z "$1" ]; then
                        echo "Usage: ./dev n8n credentials restore <backup-directory>"
                        echo ""
                        echo "Restore credentials from a backup"
                        echo ""
                        echo "Example:"
                        echo "  ./dev n8n credentials restore ./n8n/backups/credentials_20240101_120000"
                        exit 1
                    fi
                    
                    backup_dir="$1"
                    
                    if [ ! -d "$backup_dir" ]; then
                        echo -e "${RED}Error: Backup directory not found: $backup_dir${NC}"
                        exit 1
                    fi
                    
                    echo -e "${YELLOW}Warning: This will overwrite existing credentials${NC}"
                    read -p "Continue? (y/N) " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Cancelled"
                        exit 0
                    fi
                    
                    # Check for decrypted backup
                    if [ -f "$backup_dir/credentials_decrypted.json" ]; then
                        echo -e "${BLUE}Restoring from decrypted backup...${NC}"
                        docker cp "$backup_dir/credentials_decrypted.json" aletheia_development-n8n-1:/tmp/restore.json
                        docker exec aletheia_development-n8n-1 n8n import:credentials --input="/tmp/restore.json"
                    elif [ -d "$backup_dir/encrypted" ]; then
                        echo -e "${BLUE}Restoring from encrypted backup...${NC}"
                        docker cp "$backup_dir/encrypted" aletheia_development-n8n-1:/tmp/restore_enc
                        docker exec aletheia_development-n8n-1 n8n import:credentials --separate --input="/tmp/restore_enc"
                    else
                        echo -e "${RED}No valid backup files found${NC}"
                        exit 1
                    fi
                    
                    # Clean up
                    docker exec aletheia_development-n8n-1 rm -rf /tmp/restore.json /tmp/restore_enc
                    
                    echo -e "${GREEN}✓${NC} Restore completed"
                    echo "Verify with: ./dev n8n credentials list"
                    ;;
                    
                create-postgres)
                    echo -e "${BLUE}Creating Postgres credential for n8n...${NC}"
                    
                    # Check if Main workflow credential already exists
                    existing=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                        "SELECT id, name FROM credentials_entity WHERE id='PMs8mP0nYzWgEu40';" 2>/dev/null)
                    
                    if [ -n "$existing" ]; then
                        echo -e "${YELLOW}Postgres credential already exists:${NC}"
                        echo "  ID: PMs8mP0nYzWgEu40"
                        echo "  Name: Postgres Main"
                        echo ""
                        echo "This credential is already configured for the Main workflow."
                        exit 0
                    fi
                    
                    # Create credential JSON file
                    cat > /tmp/n8n_postgres_cred.json <<EOF
[
  {
    "id": "PMs8mP0nYzWgEu40",
    "name": "Postgres Main",
    "type": "postgres",
    "data": {
      "host": "db",
      "port": 5432,
      "database": "${DB_NAME:-aletheia}",
      "user": "${DB_USER:-aletheia}",
      "password": "${DB_PASSWORD:-SecurePass123}",
      "ssl": "disable"
    }
  }
]
EOF
                    
                    # Copy to container and import
                    docker cp /tmp/n8n_postgres_cred.json aletheia_development-n8n-1:/tmp/postgres_cred.json
                    
                    if docker exec aletheia_development-n8n-1 n8n import:credentials --input=/tmp/postgres_cred.json 2>&1 | grep -q "Successfully imported"; then
                        echo -e "${GREEN}✓${NC} Postgres credential created successfully!"
                        echo ""
                        echo "  ID: PMs8mP0nYzWgEu40"
                        echo "  Name: Postgres Main"
                        echo "  Host: db"
                        echo "  Database: ${DB_NAME:-aletheia}"
                        echo "  User: ${DB_USER:-aletheia}"
                        echo ""
                        echo "The Main workflow can now use this credential."
                        
                        # Clean up
                        rm -f /tmp/n8n_postgres_cred.json
                        docker exec aletheia_development-n8n-1 rm -f /tmp/postgres_cred.json 2>/dev/null || true
                    else
                        echo -e "${RED}Failed to create credential${NC}"
                        echo "Please create it manually in the n8n UI."
                        rm -f /tmp/n8n_postgres_cred.json
                        exit 1
                    fi
                    ;;
                    
                update)
                    shift
                    cred_type="$1"
                    
                    case "$cred_type" in
                        postgres)
                            echo -e "${BLUE}Updating Postgres credential from environment...${NC}"
                            
                            # Check if credential exists
                            existing=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                                "SELECT id FROM credentials_entity WHERE id='PMs8mP0nYzWgEu40';" 2>/dev/null)
                            
                            if [ -n "$existing" ]; then
                                # Delete old credential
                                docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                                    "DELETE FROM credentials_entity WHERE id='PMs8mP0nYzWgEu40';" 2>/dev/null
                            fi
                            
                            # Create updated credential
                            cat > /tmp/n8n_postgres_update.json <<EOF
[
  {
    "id": "PMs8mP0nYzWgEu40",
    "name": "Postgres Main",
    "type": "postgres",
    "data": {
      "host": "db",
      "port": 5432,
      "database": "${DB_NAME:-aletheia}",
      "user": "${DB_USER:-aletheia}",
      "password": "${DB_PASSWORD:-SecurePass123}",
      "ssl": "disable"
    }
  }
]
EOF
                            docker cp /tmp/n8n_postgres_update.json aletheia_development-n8n-1:/tmp/postgres_update.json
                            docker exec aletheia_development-n8n-1 n8n import:credentials --input=/tmp/postgres_update.json >/dev/null 2>&1
                            rm -f /tmp/n8n_postgres_update.json
                            
                            echo -e "${GREEN}✓${NC} Postgres credential updated"
                            echo "  Database: ${DB_NAME:-aletheia}"
                            echo "  User: ${DB_USER:-aletheia}"
                            ;;
                            
                        anthropic)
                            shift
                            api_key="$1"
                            
                            if [ -z "$api_key" ]; then
                                # Try to get from environment
                                api_key="$ANTHROPIC_API_KEY"
                                if [ -z "$api_key" ]; then
                                    echo -e "${RED}Error: No API key provided${NC}"
                                    echo "Usage: ./dev n8n credentials update anthropic <api-key>"
                                    echo "   Or: export ANTHROPIC_API_KEY='your-key'"
                                    exit 1
                                fi
                            fi
                            
                            echo -e "${BLUE}Updating Anthropic credential...${NC}"
                            
                            # Check if credential exists and get its ID
                            existing_id=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                                "SELECT id FROM credentials_entity WHERE type='anthropicApi' LIMIT 1;" 2>/dev/null)
                            
                            if [ -z "$existing_id" ]; then
                                existing_id="PAB7ZSRzpUCaL5VR"
                            else
                                # Delete old credential
                                docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                                    "DELETE FROM credentials_entity WHERE id='$existing_id';" 2>/dev/null
                            fi
                            
                            # Create updated credential
                            cat > /tmp/n8n_anthropic_update.json <<EOF
[
  {
    "id": "$existing_id",
    "name": "Anthropic account",
    "type": "anthropicApi",
    "data": {
      "apiKey": "$api_key"
    }
  }
]
EOF
                            docker cp /tmp/n8n_anthropic_update.json aletheia_development-n8n-1:/tmp/anthropic_update.json
                            docker exec aletheia_development-n8n-1 n8n import:credentials --input=/tmp/anthropic_update.json >/dev/null 2>&1
                            rm -f /tmp/n8n_anthropic_update.json
                            
                            echo -e "${GREEN}✓${NC} Anthropic credential updated"
                            ;;
                            
                        --all)
                            echo -e "${BLUE}Updating all credentials from environment...${NC}"
                            echo ""
                            
                            # Update Postgres
                            handle_n8n_command credentials update postgres
                            echo ""
                            
                            # Update Anthropic if key exists
                            if [ -n "$ANTHROPIC_API_KEY" ]; then
                                handle_n8n_command credentials update anthropic
                            else
                                echo -e "${YELLOW}⚠${NC} No ANTHROPIC_API_KEY in environment, skipping"
                            fi
                            
                            echo ""
                            echo -e "${GREEN}✓${NC} All credentials updated"
                            ;;
                            
                        *)
                            echo "Usage: ./dev n8n credentials update <type> [options]"
                            echo ""
                            echo "Types:"
                            echo "  postgres              - Update from DB_* env vars"
                            echo "  anthropic [api-key]   - Update with API key"
                            echo "  --all                 - Update all from environment"
                            echo ""
                            echo "Examples:"
                            echo "  ./dev n8n credentials update postgres"
                            echo "  ./dev n8n credentials update anthropic sk-ant-..."
                            echo "  ./dev n8n credentials update --all"
                            ;;
                    esac
                    ;;
                    
                delete)
                    shift
                    if [ -z "$1" ]; then
                        echo "Usage: ./dev n8n credentials delete <credential-id>"
                        echo ""
                        echo "Delete a credential by ID"
                        echo ""
                        echo "First list credentials to get IDs:"
                        echo "  ./dev n8n credentials list"
                        exit 1
                    fi
                    
                    cred_id="$1"
                    
                    echo -e "${YELLOW}Warning: This will delete credential ID: $cred_id${NC}"
                    read -p "Continue? (y/N) " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Cancelled"
                        exit 0
                    fi
                    
                    # Delete from database
                    docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                        "DELETE FROM credentials_entity WHERE id='$cred_id';"
                    
                    echo -e "${GREEN}✓${NC} Credential deleted"
                    ;;
                    
                fix-main-workflow)
                    echo -e "${BLUE}Fixing Main workflow Postgres credential...${NC}"
                    
                    # Check if Main workflow exists
                    workflow_check=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                        "SELECT id, name FROM workflow_entity WHERE name LIKE '%Main%' LIMIT 1;" 2>/dev/null)
                    
                    if [ -z "$workflow_check" ]; then
                        echo -e "${YELLOW}Main workflow not found. Import it first with:${NC}"
                        echo "  ./dev n8n workflows import"
                        exit 1
                    fi
                    
                    echo "Found workflow: $workflow_check"
                    
                    # Check for existing Postgres credential
                    existing_cred=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                        "SELECT id, name FROM credentials_entity WHERE type='postgres' AND name LIKE '%Main%' LIMIT 1;" 2>/dev/null)
                    
                    if [ -n "$existing_cred" ]; then
                        echo -e "${YELLOW}Found existing credential: $existing_cred${NC}"
                        cred_id=$(echo "$existing_cred" | cut -d'|' -f1)
                        
                        # Update the workflow to use this credential
                        echo -e "${CYAN}Updating Main workflow to use credential ID: $cred_id${NC}"
                        
                        # This would require parsing and updating the workflow JSON
                        # For now, just report the credential ID
                        echo -e "${GREEN}✓${NC} Postgres credential ready: $cred_id"
                        echo ""
                        echo "If the workflow still shows credential errors:"
                        echo "1. Open the Main workflow in n8n UI"
                        echo "2. Select the 'Postgres Chat Memory' node"
                        echo "3. Choose 'Postgres Main' from the credential dropdown"
                        echo "4. Save the workflow"
                    else
                        echo -e "${YELLOW}No Postgres credential found. Creating one...${NC}"
                        
                        # Create the credential
                        if [ -f "n8n/scripts/credential-manager.sh" ]; then
                            bash n8n/scripts/credential-manager.sh create-from-env
                        else
                            # Use inline creation
                            "$0" credentials create-postgres
                        fi
                        
                        echo ""
                        echo -e "${GREEN}✓${NC} Credential created. Now update the Main workflow:"
                        echo "1. Open http://localhost:${N8N_PORT:-8100}"
                        echo "2. Edit the Main workflow"
                        echo "3. Select 'Postgres Main' in the Postgres Chat Memory node"
                        echo "4. Save the workflow"
                    fi
                    ;;
                    
                *)
                    echo "Usage: ./dev n8n credentials <command> [options]"
                    echo ""
                    echo "Commands:"
                    echo "  list                - List all credentials"
                    echo "  export [--output DIR] - Export all credentials"
                    echo "  import <file/dir>   - Import credentials from file or directory"
                    echo "  backup              - Create full backup with decrypted data"
                    echo "  restore <dir>       - Restore from backup directory"
                    echo "  create-postgres     - Create Postgres credential"
                    echo "  update <type>       - Update credentials from environment"
                    echo "  fix-main-workflow   - Fix/create Postgres credential for Main workflow"
                    echo "  delete <id>         - Delete a credential by ID"
                    echo ""
                    echo "Examples:"
                    echo "  ./dev n8n credentials list"
                    echo "  ./dev n8n credentials create-postgres"
                    echo "  ./dev n8n credentials update postgres"
                    echo "  ./dev n8n credentials update anthropic sk-ant-..."
                    echo "  ./dev n8n credentials update --all"
                    echo "  ./dev n8n credentials backup"
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
            
        init)
            echo -e "${BLUE}═══════════════════════════════════════════${NC}"
            echo -e "${BLUE}     n8n Complete Setup Wizard${NC}"
            echo -e "${BLUE}═══════════════════════════════════════════${NC}"
            echo ""
            
            # Step 1: Check if n8n is running
            echo -e "${CYAN}Step 1/5: Checking n8n service...${NC}"
            if ! check_service_running "n8n"; then
                echo -e "${YELLOW}n8n is not running. Starting it now...${NC}"
                $DOCKER_COMPOSE up -d n8n
                sleep 5
            fi
            echo -e "${GREEN}✓${NC} n8n is running"
            echo ""
            
            # Step 2: Setup owner account
            echo -e "${CYAN}Step 2/5: Setting up owner account...${NC}"
            owner_check=$($DOCKER_COMPOSE exec -T n8n sqlite3 /data/.n8n/database.sqlite \
                "SELECT COUNT(*) FROM user WHERE role='owner';" 2>/dev/null || echo "0")
            
            if [ "$owner_check" = "0" ]; then
                echo "Creating owner account..."
                handle_n8n_command setup
            else
                echo -e "${GREEN}✓${NC} Owner account already exists"
            fi
            echo ""
            
            # Step 3: Setup Postgres credential
            echo -e "${CYAN}Step 3/5: Setting up Postgres credential...${NC}"
            postgres_check=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT id FROM credentials_entity WHERE id='PMs8mP0nYzWgEu40';" 2>/dev/null)
            
            if [ -z "$postgres_check" ]; then
                echo "Creating Postgres credential..."
                # Create the credential
                cat > /tmp/n8n_postgres_init.json <<EOF
[
  {
    "id": "PMs8mP0nYzWgEu40",
    "name": "Postgres Main",
    "type": "postgres",
    "data": {
      "host": "db",
      "port": 5432,
      "database": "${DB_NAME:-aletheia}",
      "user": "${DB_USER:-aletheia}",
      "password": "${DB_PASSWORD:-SecurePass123}",
      "ssl": "disable"
    }
  }
]
EOF
                docker cp /tmp/n8n_postgres_init.json aletheia_development-n8n-1:/tmp/postgres_init.json
                docker exec aletheia_development-n8n-1 n8n import:credentials --input=/tmp/postgres_init.json >/dev/null 2>&1
                rm -f /tmp/n8n_postgres_init.json
                echo -e "${GREEN}✓${NC} Postgres credential created"
            else
                echo -e "${GREEN}✓${NC} Postgres credential already exists"
            fi
            echo ""
            
            # Step 4: Setup Anthropic credential (if API key exists)
            echo -e "${CYAN}Step 4/5: Setting up Anthropic credential...${NC}"
            anthropic_check=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT id FROM credentials_entity WHERE type='anthropicApi';" 2>/dev/null)
            
            if [ -z "$anthropic_check" ]; then
                if [ -n "$ANTHROPIC_API_KEY" ]; then
                    echo "Creating Anthropic credential from environment..."
                    cat > /tmp/n8n_anthropic_init.json <<EOF
[
  {
    "id": "PAB7ZSRzpUCaL5VR",
    "name": "Anthropic account",
    "type": "anthropicApi",
    "data": {
      "apiKey": "$ANTHROPIC_API_KEY"
    }
  }
]
EOF
                    docker cp /tmp/n8n_anthropic_init.json aletheia_development-n8n-1:/tmp/anthropic_init.json
                    docker exec aletheia_development-n8n-1 n8n import:credentials --input=/tmp/anthropic_init.json >/dev/null 2>&1
                    rm -f /tmp/n8n_anthropic_init.json
                    echo -e "${GREEN}✓${NC} Anthropic credential created"
                else
                    echo -e "${YELLOW}⚠${NC} No ANTHROPIC_API_KEY in environment"
                    echo "  To add later: export ANTHROPIC_API_KEY='your-key' && ./dev n8n credentials update anthropic"
                fi
            else
                echo -e "${GREEN}✓${NC} Anthropic credential already exists"
            fi
            echo ""
            
            # Step 5: Import and activate Main workflow
            echo -e "${CYAN}Step 5/5: Setting up Main workflow...${NC}"
            workflow_check=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT id FROM workflow_entity WHERE name='Main';" 2>/dev/null)
            
            if [ -z "$workflow_check" ]; then
                if [ -f "n8n/workflows/Main.json" ]; then
                    echo "Importing Main workflow..."
                    docker cp n8n/workflows/Main.json aletheia_development-n8n-1:/tmp/Main.json
                    docker exec aletheia_development-n8n-1 n8n import:workflow --input=/tmp/Main.json >/dev/null 2>&1
                    docker exec aletheia_development-n8n-1 n8n update:workflow --id=5bmVEfcZjJ7tq6rx --active=true >/dev/null 2>&1
                    echo -e "${GREEN}✓${NC} Main workflow imported and activated"
                else
                    echo -e "${YELLOW}⚠${NC} Main workflow file not found"
                fi
            else
                echo -e "${GREEN}✓${NC} Main workflow already exists"
            fi
            echo ""
            
            # Final validation
            echo -e "${CYAN}Running validation...${NC}"
            "$0" validate --quiet
            echo ""
            
            echo -e "${GREEN}════════════════════════════════════════════${NC}"
            echo -e "${GREEN}     n8n Setup Complete!${NC}"
            echo -e "${GREEN}════════════════════════════════════════════${NC}"
            echo ""
            echo "Access n8n at: ${BLUE}http://localhost:${N8N_PORT:-8100}${NC}"
            echo ""
            echo "Next steps:"
            echo "  • Test the Main workflow"
            echo "  • Add additional credentials as needed"
            echo "  • Import more workflows with: ./dev n8n workflows import"
            ;;
            
        validate)
            quiet_mode=false
            if [ "$1" = "--quiet" ]; then
                quiet_mode=true
                shift
            fi
            
            if [ "$quiet_mode" = false ]; then
                echo -e "${BLUE}═══════════════════════════════════════════${NC}"
                echo -e "${BLUE}     n8n Health & Validation Check${NC}"
                echo -e "${BLUE}═══════════════════════════════════════════${NC}"
                echo ""
            fi
            
            validation_passed=true
            
            # Check 1: Service running
            if [ "$quiet_mode" = false ]; then
                echo -e "${CYAN}1. Service Status:${NC}"
            fi
            if check_service_running "n8n" 2>/dev/null; then
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${GREEN}✓${NC} n8n container is running"
                fi
            else
                echo -e "   ${RED}✗${NC} n8n container is not running"
                echo -e "   ${YELLOW}Fix:${NC} ./dev up n8n"
                validation_passed=false
            fi
            
            # Check 2: Database connectivity
            if [ "$quiet_mode" = false ]; then
                echo -e "${CYAN}2. Database Connectivity:${NC}"
            fi
            if docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite "SELECT 'OK';" >/dev/null 2>&1; then
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${GREEN}✓${NC} SQLite database accessible"
                fi
            else
                echo -e "   ${RED}✗${NC} Cannot access n8n database"
                validation_passed=false
            fi
            
            # Check 3: Credentials validation
            if [ "$quiet_mode" = false ]; then
                echo -e "${CYAN}3. Credentials Check:${NC}"
            fi
            
            # Check Postgres credential
            postgres_cred=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT id FROM credentials_entity WHERE id='PMs8mP0nYzWgEu40';" 2>/dev/null)
            if [ -n "$postgres_cred" ]; then
                # Try to decrypt it
                if docker exec aletheia_development-n8n-1 n8n export:credentials --id=PMs8mP0nYzWgEu40 --decrypted >/dev/null 2>&1; then
                    if [ "$quiet_mode" = false ]; then
                        echo -e "   ${GREEN}✓${NC} Postgres credential valid"
                    fi
                else
                    echo -e "   ${RED}✗${NC} Postgres credential cannot be decrypted"
                    echo -e "   ${YELLOW}Fix:${NC} ./dev n8n credentials create-postgres"
                    validation_passed=false
                fi
            else
                echo -e "   ${YELLOW}⚠${NC} Postgres credential missing"
                echo -e "   ${YELLOW}Fix:${NC} ./dev n8n credentials create-postgres"
                validation_passed=false
            fi
            
            # Check Anthropic credential
            anthropic_cred=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT COUNT(*) FROM credentials_entity WHERE type='anthropicApi';" 2>/dev/null)
            if [ "$anthropic_cred" -gt "0" ]; then
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${GREEN}✓${NC} Anthropic credential exists"
                fi
            else
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${YELLOW}⚠${NC} No Anthropic credential"
                fi
            fi
            
            # Check 4: Workflow validation
            if [ "$quiet_mode" = false ]; then
                echo -e "${CYAN}4. Workflow Check:${NC}"
            fi
            
            main_workflow=$(docker exec aletheia_development-n8n-1 sqlite3 /data/.n8n/database.sqlite \
                "SELECT active FROM workflow_entity WHERE name='Main';" 2>/dev/null)
            if [ "$main_workflow" = "1" ]; then
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${GREEN}✓${NC} Main workflow is active"
                fi
            elif [ -n "$main_workflow" ]; then
                echo -e "   ${YELLOW}⚠${NC} Main workflow exists but is inactive"
                echo -e "   ${YELLOW}Fix:${NC} ./dev n8n workflows activate Main"
            else
                echo -e "   ${RED}✗${NC} Main workflow not found"
                echo -e "   ${YELLOW}Fix:${NC} ./dev n8n workflows import"
                validation_passed=false
            fi
            
            # Check 5: Webhook endpoint
            if [ "$quiet_mode" = false ]; then
                echo -e "${CYAN}5. Webhook Endpoint:${NC}"
            fi
            webhook_url="http://localhost:${N8N_PORT:-8100}/webhook/${N8N_WEBHOOK_ID}"
            if curl -s -o /dev/null -w "%{http_code}" "$webhook_url" 2>/dev/null | grep -q "404"; then
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${GREEN}✓${NC} Webhook endpoint reachable"
                fi
            else
                if [ "$quiet_mode" = false ]; then
                    echo -e "   ${YELLOW}⚠${NC} Webhook may not be configured"
                fi
            fi
            
            # Summary
            if [ "$quiet_mode" = false ]; then
                echo ""
                if [ "$validation_passed" = true ]; then
                    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
                    echo -e "${GREEN}     All validations passed!${NC}"
                    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
                else
                    echo -e "${YELLOW}═══════════════════════════════════════════${NC}"
                    echo -e "${YELLOW}     Some issues need attention${NC}"
                    echo -e "${YELLOW}═══════════════════════════════════════════${NC}"
                    echo ""
                    echo "Run the suggested fix commands above, or:"
                    echo "  ./dev n8n init   # To run complete setup"
                fi
            else
                # Quiet mode - just return status
                if [ "$validation_passed" = true ]; then
                    echo -e "${GREEN}✓${NC} All validations passed"
                else
                    echo -e "${RED}✗${NC} Validation failed - run './dev n8n validate' for details"
                fi
            fi
            ;;
            
        shell)
            echo -e "${BLUE}Opening n8n shell...${NC}"
            $DOCKER_COMPOSE exec n8n /bin/sh
            ;;
            
        *)
            echo "Usage: ./dev n8n <command>"
            echo ""
            echo "Commands:"
            echo "  init         - Complete setup wizard (recommended for first time)"
            echo "  validate     - Health check and validation"
            echo "  setup        - Run initial n8n owner account setup"
            echo "  workflows    - Manage n8n workflows"
            echo "  nodes        - Manage custom nodes"
            echo "  credentials  - Manage credentials"
            echo "  config       - Manage n8n configuration"
            echo "  logs         - Show n8n logs"
            echo "  shell        - Open n8n container shell"
            echo ""
            echo "Quick Start:"
            echo "  ./dev n8n init      # Complete setup wizard"
            echo "  ./dev n8n validate  # Check everything is working"
            echo ""
            echo "Examples:"
            echo "  ./dev n8n workflows list"
            echo "  ./dev n8n credentials update --all"
            echo "  ./dev n8n nodes build"
            ;;
    esac
}