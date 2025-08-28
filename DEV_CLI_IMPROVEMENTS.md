# Dev CLI Improvement Recommendations

## Critical Fixes Needed

### 1. Fix Dependency Detection (dev-deps.sh)
**Problem:** Not detecting any service dependencies
**Solution:** Update parsing to handle extended depends_on format:
```yaml
depends_on:
  db:
    condition: service_started
```

### 2. Implement N8N Commands (dev-n8n.sh)
**Problem:** All subcommands just show help
**Solution:** Implement actual functionality for:
- `workflows list/import/export/execute`
- `credentials backup/restore`
- `monitor executions`
- `query status`

### 3. Fix Reconcile Container Mapping
**Problem:** Container names don't match service names
**Solution:** Check both service name and container_name field

### 4. Fix Audit Env Default Handling
**Problem:** Variables with defaults shown as undefined
**Solution:** Parse and respect default values in docker-compose.yml

### 5. Fix Health Check Service List
**Problem:** Checking all services instead of core ones
**Solution:** Define core service list in dev-doctor.sh

## Nice-to-Have Improvements

### 1. Add Progress Indicators
- Long-running commands (rebuild, backup) need progress bars
- Use spinner for commands that take >2 seconds

### 2. Add JSON Output Mode Consistency
- Some commands don't properly support --json flag
- Standardize JSON output format across all commands

### 3. Add Command Aliases
- `./dev ps` → `./dev status`
- `./dev log` → `./dev logs`
- `./dev exec` → `./dev shell`

### 4. Add Smart Suggestions
- When a service fails, suggest the fix
- When ports are in use, show what's using them
- When .env is missing values, offer to generate them

### 5. Add Batch Operations
- `./dev restart all` - Restart all services
- `./dev logs --tail 50 all` - Show logs from all services
- `./dev backup --all` - Backup database, configs, and volumes

## Performance Optimizations

### 1. Cache Docker Compose Config
- Parse once per session instead of multiple times
- Store in temp file with timestamp

### 2. Parallelize Health Checks
- Check multiple services simultaneously
- Use background jobs with timeout

### 3. Lazy Load Modules
- Only source modules when needed
- Reduce startup time for simple commands

## Code Quality Improvements

### 1. Standardize Exit Codes
- Use consistent exit codes across all modules
- Document exit code meanings

### 2. Add Unit Tests
- Create test suite for each module
- Test edge cases and error conditions

### 3. Improve Error Messages
- Add context to errors
- Suggest fixes for common problems
- Include relevant log snippets

### 4. Add Debug Mode
- `DEV_DEBUG=1 ./dev status` for verbose output
- Log all commands executed
- Show timing information

## Priority Order

1. **High Priority** (Breaking functionality)
   - Fix dependency detection
   - Implement n8n commands
   - Fix reconcile container mapping

2. **Medium Priority** (Usability issues)
   - Fix audit env defaults
   - Fix health check service list
   - Add progress indicators

3. **Low Priority** (Nice-to-haves)
   - Add command aliases
   - Add smart suggestions
   - Performance optimizations