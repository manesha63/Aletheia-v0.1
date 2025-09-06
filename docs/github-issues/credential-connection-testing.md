# n8n Credential Connection Testing

## Issue Summary
n8n does not provide a straightforward way to programmatically test credential connections from the command line or API. This makes it difficult to validate credentials during automated setup.

## Current Challenge
When setting up credentials via `n8n import:credentials`, there's no built-in way to verify that the credentials actually work until a workflow tries to use them.

## Attempted Solutions

### 1. Direct Connection Test (PostgreSQL)
Tried to test PostgreSQL connections using Node.js pg library:
```javascript
const { Client } = require('pg');
const client = new Client({
    host: 'db',
    port: 5432,
    database: 'aletheia',
    user: 'aletheia',
    password: 'aletheia_secure_pw_2024'
});
client.connect()
```
**Result**: n8n container doesn't have the pg library in the global scope

### 2. UI Connection Test
The n8n UI shows a "Connection Test" button for credentials, but this is not accessible via CLI or API.

### 3. Workflow Execution Test
Creating a test workflow that uses the credential and checking if it executes successfully.
**Challenge**: Requires creating, executing, and parsing workflow results - complex for simple validation.

## Workaround
Currently, we:
1. Create credentials with known-good parameters
2. Trust that if the import succeeds, the credentials will work
3. Monitor workflow execution logs for authentication errors
4. Provide clear error messages if credentials fail

## Proposed Solutions

### Short-term
1. Add validation logic in `manage-credentials.sh` that tests connections using available tools
2. Parse n8n logs for credential-related errors after workflow execution
3. Create a simple test workflow that validates each credential type

### Long-term
1. Request n8n feature: CLI command for credential testing
   ```bash
   n8n test:credential --id=<credential-id>
   ```

2. Request n8n feature: API endpoint for credential validation
   ```
   POST /api/v1/credentials/{id}/test
   ```

3. Create a custom n8n node that reports credential status

## Impact
- **Development**: Harder to debug credential issues during setup
- **User Experience**: Users may not know credentials are misconfigured until workflow execution
- **Automation**: Cannot fully automate credential validation in CI/CD pipelines

## Related Files
- `/n8n/scripts/manage-credentials.sh` - Current credential management
- `/n8n/scripts/setup-credentials.sh` - Basic credential setup
- `docker-compose.yml` - Environment variable passing

## Priority
Medium - The system works but lacks confidence in credential validity during setup