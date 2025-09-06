#!/bin/sh
# Clean n8n entrypoint - delegates to single startup script

echo "🚀 n8n Starting..."

# Fix custom nodes first
if [ -f /fix-custom-nodes.sh ]; then
    /fix-custom-nodes.sh
fi

# Use single unified startup script
if [ -f /scripts/single-startup.sh ]; then
    exec /scripts/single-startup.sh
else
    # Fallback if single startup not found
    exec /usr/local/bin/dev-startup
fi