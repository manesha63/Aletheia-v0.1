# n8n Authentication Bypass Implementation

## Overview
This implementation allows n8n to work programmatically without requiring manual UI login. It automatically creates an API key during startup that can be used for webhook access and API calls.

## How It Works

### 1. Automatic Setup During `./dev up`
When you run `./dev up`, the following happens automatically:

1. **n8n starts** with the regular initialization process
2. **Owner account is created** (velvetmoon222999@gmail.com / admin123)
3. **Workflows are imported** from the `workflow_json` directory
4. **Credentials are configured** from environment variables
5. **API key is generated** and stored in the database
6. **Authentication bypass is activated** via the auto-login script

### 2. Files Involved

- **`n8n/scripts/auto-login.sh`**: Core authentication bypass logic
  - Generates and stores API key
  - Attempts programmatic login
  - Configures webhook access
  
- **`n8n/scripts/single-startup.sh`**: Modified to run auto-login
  - Calls auto-login.sh after n8n initialization
  - Waits for authentication setup to complete
  
- **`dev-modules/dev-n8n.sh`**: Updated webhook test
  - Automatically uses API key if available
  - Falls back to unauthenticated request if no key
  
- **`Dockerfile.n8n`**: Updated to include new scripts
  - Copies auto-login.sh to container
  - Installs required tools (openssl for key generation)

### 3. API Key Storage

The API key is stored in multiple places for reliability:
- **Database**: In the `user` table's `apiKey` field
- **File**: `/data/.n8n/.api-key` (persists across restarts)
- **Environment**: Exported as `N8N_API_KEY` during session

### 4. Testing Webhook Access

After running `./dev up`, test webhook access:

```bash
# This will automatically use the API key
./dev n8n test webhook

# Or test manually
curl -X POST http://localhost:8100/webhook/c188c31c-1c45-4118-9ece-5b6057ab5177 \
  -H "Content-Type: application/json" \
  -H "X-N8N-API-KEY: $(docker exec aletheia_development-n8n-1 cat /data/.n8n/.api-key)" \
  -d '{"message":"Hello"}'
```

### 5. Troubleshooting

If webhook access isn't working:

1. **Check if API key was created**:
   ```bash
   ./dev exec n8n cat /data/.n8n/.api-key
   ```

2. **Verify API key in database**:
   ```bash
   ./dev exec n8n sqlite3 /data/.n8n/database.sqlite "SELECT apiKey FROM user WHERE role='global:owner'"
   ```

3. **Check auto-login logs**:
   ```bash
   ./dev logs n8n | grep "auto-login"
   ```

4. **Validate webhook access**:
   ```bash
   ./dev exec n8n /scripts/validate-webhook-access.sh
   ```

### 6. How the Bypass Works

n8n has two authentication mechanisms:
1. **Session-based** (cookies) - requires UI login
2. **API key-based** - bypasses UI login

This implementation uses the API key mechanism:
- API keys are stored in the user record
- The `X-N8N-API-KEY` header authenticates requests
- Webhooks accept API key authentication
- No UI login is required when using API keys

### 7. Fresh Installation

On a fresh clone of the repository:

1. Run `./dev up` - everything is automatic
2. Wait for services to start (~30 seconds)
3. Test with `./dev n8n test webhook`
4. The webhook should work immediately without manual login

### 8. Security Notes

- API keys are generated using cryptographically secure random data
- Keys are stored with restricted permissions (600)
- Each n8n instance gets a unique API key
- Keys persist across container restarts

## Summary

This solution completely bypasses the n8n login requirement by:
1. Automatically generating an API key during startup
2. Storing it persistently in the database and filesystem
3. Using it for all programmatic access (webhooks, API calls)
4. Integrating seamlessly with the `./dev` CLI tool

Users never need to manually log in to n8n for the system to work.