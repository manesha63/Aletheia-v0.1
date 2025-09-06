#!/bin/sh
# Simplified n8n entrypoint for development

echo "🚀 n8n Development Mode"

# Run auto-setup in background after n8n starts
(
    sleep 60  # Give n8n time to fully initialize
    
    # Check if already set up
    if [ -f /data/.n8n/.setup-complete ]; then
        echo "Setup already complete" >> /tmp/n8n-setup.log
    else
        # Run auto-setup for user creation and workflow import
        if [ -f /usr/local/bin/auto-setup ]; then
            echo "Running auto-setup..." >> /tmp/n8n-setup.log
            /usr/local/bin/auto-setup >> /tmp/n8n-setup.log 2>&1
            
            # Mark as complete
            touch /data/.n8n/.setup-complete
        fi
    fi
) &

# Fix custom nodes and start n8n
if [ -f /fix-custom-nodes.sh ]; then
    exec /fix-custom-nodes.sh
else
    exec n8n
fi