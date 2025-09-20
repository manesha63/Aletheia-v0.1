# n8n Startup Flow

## Overview
The n8n service has been configured for automatic setup and credential configuration on startup.

## Startup Sequence

1. **Docker Container Start** (`./dev up n8n`)
   - Builds image with Dockerfile.n8n
   - Mounts volumes:
     - `n8n_data:/data` - Persistent storage
     - `./n8n/scripts:/scripts:ro` - Startup scripts
     - `./workflow_json:/workflow_json:ro` - Workflow definitions

2. **Entrypoint Execution** (`/entrypoint.sh`)
   - Runs `/fix-custom-nodes.sh` to fix custom node loading
   - Executes `/scripts/single-startup.sh` (primary startup script)

3. **Single Startup Script** (`single-startup.sh`)
   - Starts n8n in background
   - Waits for database initialization
   - Creates owner account (if not exists):
     - Email: velvetmoon222999@gmail.com
     - Password: admin123
   - Cleans up duplicate workflows (keeps only "central")
   - Imports workflows from `/workflow_json/`
   - Creates credentials from environment:
     - PostgreSQL (from DB_* vars)
     - Anthropic (if ANTHROPIC_API_KEY is set)
     - OpenAI (if OPENAI_API_KEY is set)
   - Activates workflows
   - Restarts n8n in foreground

## Required Environment Variables

Set these in `.env`:
```bash
# Database (required)
DB_USER=aletheia
DB_PASSWORD=your_password
DB_NAME=aletheia
DB_HOST=db
DB_PORT=5432

# API Keys (optional but recommended)
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key

# n8n Configuration
N8N_ENCRYPTION_KEY=your_encryption_key
N8N_WEBHOOK_ID=c188c31c-1c45-4118-9ece-5b6057ab5177
```

## Testing

After startup, test the webhook:
```bash
./dev n8n test webhook
```

## Known Issues

1. **UI Login Required**: n8n v1.99.1 requires authentication for the UI. Use the credentials above.
2. **Auth Bypass**: Environment variables `N8N_USER_MANAGEMENT_DISABLED` and `N8N_AUTH_ENABLED` are set but ignored by n8n 1.x.

## Troubleshooting

If credentials aren't created automatically:
```bash
./dev n8n credentials update postgres
./dev n8n credentials update anthropic
```

Check logs:
```bash
./dev n8n logs
```

## Files

- `/n8n/entrypoint.sh` - Container entrypoint
- `/n8n/scripts/single-startup.sh` - Main startup script
- `/n8n/fix-custom-nodes.sh` - Fixes custom node loading
- `/workflow_json/central-workflow.json` - Main workflow definition