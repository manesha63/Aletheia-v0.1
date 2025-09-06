#!/bin/sh
# Import workflows using n8n CLI after n8n is running

echo "Importing workflows via n8n CLI..."

# Wait a bit for n8n to be fully ready
sleep 5

# Import each workflow file
for workflow_file in /workflows/*.json; do
    if [ -f "$workflow_file" ]; then
        basename=$(basename "$workflow_file")
        echo "Importing: $basename"
        n8n import:workflow --input="$workflow_file" 2>&1 | grep -E "(Success|Error|imported)" || echo "  Import attempted"
    fi
done

# Activate all workflows
echo "Activating workflows..."
n8n update:workflow --all --active=true 2>/dev/null || true

echo "Workflow import complete!"