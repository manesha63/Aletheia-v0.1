# Phase 1: Implement Hot-Reload Custom Node Architecture

## Overview
Enable hot-reload development environment for custom nodes by implementing direct volume mounting instead of runtime copying. This eliminates startup overhead and enables immediate node updates during development.

**Priority**: Medium  
**Difficulty**: Easy  
**Estimated Time**: 1-2 hours  
**Impact**: High developer experience improvement

## Current Problem
- Custom nodes are copied from `/usr/local/lib/node_modules/n8n-nodes-*` to `/data/.n8n/custom/` on every container startup
- No hot-reload capability - requires full Docker rebuild for node changes
- Slower startup times due to runtime copying
- Complex restoration logic in startup scripts

## Solution
Replace runtime copying with direct volume mounts of compiled `dist` directories.

## Files to Modify

### 1. `docker-compose.yml` ⚠️ **CRITICAL**
**Location**: `/docker-compose.yml` (lines ~119-121)

**Current**:
```yaml
tmpfs:
  - /data:uid=${N8N_CONTAINER_UID:-1000},gid=${N8N_CONTAINER_GID:-1000}
```

**Change to**:
```yaml
volumes:
  # Mount compiled custom node dist directories directly
  - ./n8n/custom-nodes/n8n-nodes-haystack/dist:/data/.n8n/custom/haystack:ro
  - ./n8n/custom-nodes/n8n-nodes-deepseek/dist:/data/.n8n/custom/deepseek:ro
  - ./n8n/custom-nodes/n8n-nodes-citationchecker/dist:/data/.n8n/custom/citationchecker:ro
  - ./n8n/custom-nodes/n8n-nodes-citation-gen/dist:/data/.n8n/custom/citation-gen:ro
  - ./n8n/custom-nodes/n8n-nodes-hierarchicalSummarization/dist:/data/.n8n/custom/hierarchical:ro
  - ./n8n/custom-nodes/n8n-nodes-unstructured/dist:/data/.n8n/custom/unstructured:ro
  - ./n8n/custom-nodes/n8n-nodes-yake/dist:/data/.n8n/custom/yake:ro
tmpfs:
  # Selective tmpfs - only for n8n config/state, not custom nodes
  - /data/.n8n/config:uid=${N8N_CONTAINER_UID:-1000},gid=${N8N_CONTAINER_GID:-1000}
  - /data/.n8n/nodes:uid=${N8N_CONTAINER_UID:-1000},gid=${N8N_CONTAINER_GID:-1000}
```

### 2. `n8n/scripts/single-startup.sh` ⚠️ **REMOVE LOGIC**
**Location**: `/n8n/scripts/single-startup.sh` (lines 314-330)

**Remove**:
```bash
# Restore custom nodes from global node_modules to tmpfs location
log_info "Restoring custom nodes from global modules..."
restored_count=0
for node_dir in /usr/local/lib/node_modules/n8n-nodes-*; do
    if [ -d "$node_dir" ]; then
        node_name=$(basename "$node_dir")
        cp -r "$node_dir" "/data/.n8n/custom/"
        log_success "Restored: $node_name"
        restored_count=$((restored_count + 1))
    fi
done

if [ $restored_count -gt 0 ]; then
    log_success "Restored $restored_count custom nodes"
else
    log_warning "No custom nodes found to restore"
fi
```

**Replace with**:
```bash
# Custom nodes now mounted directly via Docker volumes - no restoration needed
log_info "Custom nodes loaded via direct volume mounts"
```

### 3. `n8n/entrypoint.sh` ⚠️ **OPTIONAL**  
**Location**: `/n8n/entrypoint.sh` (lines 11-14)

**Current** (already correct - no change needed):
```bash
# Fix custom nodes not needed - using direct volume mounts
# if [ -f /fix-custom-nodes.sh ]; then
#     /fix-custom-nodes.sh
# fi
```

## Files to Review
- `Dockerfile.n8n` - No changes needed, but verify custom node build process still works
- `docker-compose.yml` - Test all volume mounts work correctly
- `.env` file - Ensure `N8N_CONTAINER_UID` and `N8N_CONTAINER_GID` are set correctly

## Testing Steps

### 1. Pre-Implementation Test
```bash
# Verify current working state
docker-compose ps n8n
curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/
```

### 2. Implementation
```bash
# Stop n8n
docker-compose down n8n

# Apply changes to docker-compose.yml and single-startup.sh

# Restart n8n
docker-compose up -d n8n

# Wait for startup
sleep 30
```

### 3. Validation
```bash
# Check n8n is accessible
curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/

# Verify custom nodes are loaded
docker-compose exec n8n ls -la /data/.n8n/custom/

# Check for .node.js files
docker-compose exec n8n find /data/.n8n/custom -name "*.node.js"

# Test hot-reload: Touch a local file and verify container sees change
touch n8n/custom-nodes/n8n-nodes-haystack/dist/test.txt
docker-compose exec n8n ls -la /data/.n8n/custom/haystack/
```

### 4. Rollback Plan
If issues occur, revert changes and use:
```bash
git checkout HEAD -- docker-compose.yml n8n/scripts/single-startup.sh
docker-compose restart n8n
```

## Expected Benefits
- ✅ **Hot-reload capability** - Edit nodes locally, see changes immediately
- ✅ **Faster startup** - No runtime copying overhead
- ✅ **Cleaner architecture** - Direct mounts vs complex restoration
- ✅ **Better development workflow** - No Docker rebuilds needed for node changes

## Risks
- ⚠️ **Medium Risk** - Changes core container startup logic
- ⚠️ **File permissions** - Ensure UID/GID mapping works correctly
- ⚠️ **tmpfs conflicts** - May need adjustment if n8n expects certain directory structure

## Success Criteria
- [ ] n8n starts successfully with new volume mounts
- [ ] All custom nodes appear in n8n interface
- [ ] HTTP 200 response from http://localhost:8100/
- [ ] Local file changes appear immediately in container
- [ ] Startup time improved (measurably faster)

## Related Issues
- Prerequisite for Phase 2: Multi-path custom node loading
- Addresses technical debt from current runtime copying approach