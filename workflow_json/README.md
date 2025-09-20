# n8n Workflow Templates

This directory contains the clean n8n workflow templates for the Aletheia system.

## Current Workflows

### main-workflow-clean.json
The main workflow that handles webhook requests at path: `c188c31c-1c45-4118-9ece-5b6057ab5177`

**Features:**
- Webhook endpoint for receiving messages
- Postgres Chat Memory for conversation persistence
- AI Agent with Anthropic Claude integration
- Legal document search capabilities (requires Basic Search Workflow)

**Credentials Required:**
- PostgreSQL database connection
- Anthropic API key

## Important Notes

1. **Manual Import Only**: Workflows are NOT automatically imported to avoid corruption issues
2. **Clean State**: All corrupted workflows have been removed
3. **Single Workflow**: Only the Main Workflow is maintained as the primary interface

## How to Use

1. Access n8n at http://localhost:8100
2. Login with: velvetmoon222999@gmail.com / admin123
3. Import the workflow if needed:
   ```bash
   ./dev n8n workflows import workflow_json/main-workflow-clean.json
   ```
4. Ensure credentials are configured:
   - PostgreSQL: Should be auto-configured
   - Anthropic: Add your API key if not present

## Webhook Testing

Test the webhook endpoint:
```bash
./dev n8n test webhook
```

Or manually:
```bash
curl -X POST http://localhost:8100/webhook/c188c31c-1c45-4118-9ece-5b6057ab5177 \
  -H "Content-Type: application/json" \
  -d '{"sessionKey":"test-session","message":"Hello"}'
```

## Workflow Development

When creating or modifying workflows:
1. Always export clean versions to this directory
2. Avoid using custom nodes that may not be available
3. Test thoroughly before committing
4. Document any new credential requirements