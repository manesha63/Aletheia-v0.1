#!/bin/bash
# Clean n8n initialization script - delegates to unified setup

set -e

echo "[n8n-init] Starting n8n with unified setup..."

# Function to wait for n8n
wait_for_n8n() {
    local max_attempts=30
    local attempt=0
    
    echo "[n8n-init] Waiting for n8n to be ready..."
    
    while [ $attempt -lt $max_attempts ]; do
        if wget -q --spider http://localhost:5678/healthz 2>/dev/null || \
           wget -q --spider http://localhost:5678/ 2>/dev/null; then
            echo "[n8n-init] n8n is ready!"
            return 0
        fi
        
        echo "[n8n-init] Waiting... (attempt $((attempt+1))/$max_attempts)"
        sleep 2
        attempt=$((attempt+1))
    done
    
    echo "[n8n-init] ERROR: n8n did not start in time"
    return 1
}

# Main execution
main() {
    # Start n8n in background
    echo "[n8n-init] Starting n8n in background..."
    n8n start &
    N8N_PID=$!
    
    # Wait for n8n to be ready
    if ! wait_for_n8n; then
        kill $N8N_PID 2>/dev/null || true
        exit 1
    fi
    
    # Run unified setup
    if [ -f "/scripts/unified-setup.sh" ]; then
        echo "[n8n-init] Running unified setup..."
        /scripts/unified-setup.sh
    else
        echo "[n8n-init] WARNING: unified-setup.sh not found"
    fi
    
    # Kill background n8n
    echo "[n8n-init] Stopping background n8n..."
    kill $N8N_PID 2>/dev/null || true
    wait $N8N_PID 2>/dev/null || true
    
    # Copy database to persistent volume
    if [ -f "/home/node/.n8n/database.sqlite" ]; then
        cp /home/node/.n8n/database.sqlite /data/database.sqlite 2>/dev/null || true
    fi
    
    # Start n8n in foreground
    echo "[n8n-init] Starting n8n in foreground..."
    
    # Set up trap to copy database on exit
    trap 'cp /home/node/.n8n/database.sqlite /data/database.sqlite 2>/dev/null || true' EXIT
    
    exec n8n start
}

# Run main function
main