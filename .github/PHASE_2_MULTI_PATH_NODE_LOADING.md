# Phase 2: Multi-Path Custom Node Loading Architecture

## Overview
Implement hybrid stable/development custom node architecture using n8n's native multi-directory support. This creates clean separation between production-ready nodes and development nodes while enabling n8n's built-in hot-reload functionality.

**Priority**: Low-Medium  
**Difficulty**: Easy  
**Estimated Time**: 2-3 hours  
**Impact**: Clean architecture + production/dev separation  
**Depends on**: Phase 1 (Hot-Reload Custom Nodes)

## Current Problem
- All custom nodes treated equally - no separation of stable vs development
- Single custom directory makes it hard to manage different node states
- No clear path for promoting nodes from development to stable

## Solution
Use n8n's native `N8N_CUSTOM_EXTENSIONS` semicolon-separated path support to create stable/dev separation.

## n8n Source Code Reference
**From investigation of n8n 1.99.1 source**:
- File: `/usr/local/lib/node_modules/n8n/dist/load-nodes-and-credentials.js`
- Function: `getCustomDirectories()`
- Supports: `process.env[CUSTOM_EXTENSION_ENV].split(';')` where `CUSTOM_EXTENSION_ENV = 'N8N_CUSTOM_EXTENSIONS'`

## Files to Modify

### 1. `docker-compose.yml` ⚠️ **REPLACE PHASE 1 CHANGES**
**Location**: `/docker-compose.yml` 

**Current Environment**:
```yaml
environment:
  - N8N_CUSTOM_EXTENSIONS=/data/.n8n/custom
```

**Change to**:
```yaml
environment:
  - N8N_CUSTOM_EXTENSIONS=/data/.n8n/stable;/data/.n8n/dev
```

**Current Volumes** (from Phase 1):
```yaml
volumes:
  - ./n8n/custom-nodes/n8n-nodes-haystack/dist:/data/.n8n/custom/haystack:ro
  # ... other mounts
```

**Change to**:
```yaml
volumes:
  # Stable nodes - production ready
  - ./n8n/stable-nodes:/data/.n8n/stable:ro
  # Development nodes - active development
  - ./n8n/dev-nodes:/data/.n8n/dev:ro
```

### 2. Create New Directory Structure
**New directories to create**:
```bash
mkdir -p n8n/stable-nodes n8n/dev-nodes
```

### 3. Organize Existing Nodes
**Move stable nodes** (tested, working):
```bash
# Move production-ready nodes
mv n8n/custom-nodes/n8n-nodes-haystack n8n/stable-nodes/
mv n8n/custom-nodes/n8n-nodes-deepseek n8n/stable-nodes/
mv n8n/custom-nodes/n8n-nodes-citationchecker n8n/stable-nodes/
```

**Move development nodes** (experimental, under development):
```bash
# Move nodes still under development
mv n8n/custom-nodes/n8n-nodes-citation-gen n8n/dev-nodes/
mv n8n/custom-nodes/n8n-nodes-hierarchicalSummarization n8n/dev-nodes/
mv n8n/custom-nodes/n8n-nodes-unstructured n8n/dev-nodes/
mv n8n/custom-nodes/n8n-nodes-yake n8n/dev-nodes/
```

## Files to Create

### 1. `n8n/stable-nodes/README.md`
```markdown
# Stable Custom Nodes

Production-ready custom nodes that have been tested and are reliable for use.

## Nodes
- **n8n-nodes-haystack**: RAG and document search (✅ Working)
- **n8n-nodes-deepseek**: DeepSeek R1 AI integration (✅ Working)  
- **n8n-nodes-citationchecker**: Legal citation verification (✅ Working)

## Promotion Criteria
Nodes are moved here from `/dev-nodes/` when they meet:
- [ ] Full TypeScript compilation without errors
- [ ] All operations tested and working
- [ ] No runtime dependency issues
- [ ] Documentation complete
```

### 2. `n8n/dev-nodes/README.md`
```markdown
# Development Custom Nodes

Custom nodes under active development. May have issues or incomplete features.

## Nodes
- **n8n-nodes-citation-gen**: Citation generation (⚠️ In Development)
- **n8n-nodes-hierarchicalSummarization**: Document hierarchy (⚠️ In Development)
- **n8n-nodes-unstructured**: Unstructured data processing (⚠️ In Development)
- **n8n-nodes-yake**: Keyword extraction (⚠️ In Development)

## Development Guidelines
1. Test thoroughly before promoting to stable
2. Document known issues in node README
3. Ensure proper TypeScript compilation
```

## Files to Review
- `Dockerfile.n8n` - Update build process to handle new directory structure
- Development workflow scripts - Update any scripts that reference old paths

## Testing Steps

### 1. Pre-Implementation
```bash
# Document current state
docker-compose exec n8n ls -la /data/.n8n/custom/
docker-compose exec n8n find /data/.n8n/custom -name "*.node.js" | wc -l
```

### 2. Implementation
```bash
# Stop n8n
docker-compose down n8n

# Create new directory structure
mkdir -p n8n/stable-nodes n8n/dev-nodes

# Move nodes to appropriate directories (see above)

# Update docker-compose.yml environment and volumes

# Restart n8n
docker-compose up -d n8n

# Wait for startup
sleep 30
```

### 3. Validation
```bash
# Check both directories are loaded
docker-compose exec n8n ls -la /data/.n8n/stable/
docker-compose exec n8n ls -la /data/.n8n/dev/

# Count total nodes (should match previous count)
docker-compose exec n8n find /data/.n8n/stable -name "*.node.js" | wc -l
docker-compose exec n8n find /data/.n8n/dev -name "*.node.js" | wc -l

# Test n8n interface
curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/

# Test hot-reload on both directories
touch n8n/stable-nodes/n8n-nodes-haystack/dist/test-stable.txt
touch n8n/dev-nodes/n8n-nodes-citation-gen/dist/test-dev.txt
docker-compose exec n8n ls /data/.n8n/stable/n8n-nodes-haystack/dist/test-stable.txt
docker-compose exec n8n ls /data/.n8n/dev/n8n-nodes-citation-gen/dist/test-dev.txt
```

### 4. Hot-Reload Testing
n8n 1.99.1 includes `setupHotReload()` method that should automatically detect changes:
```bash
# Edit a stable node file and check for reload
echo "// test change" >> n8n/stable-nodes/n8n-nodes-haystack/dist/index.js

# Check n8n logs for hot-reload messages
docker-compose logs n8n --tail=20 | grep -i "reload\|updated"
```

## Expected Benefits
- ✅ **Clean separation** - Stable vs development nodes
- ✅ **Native n8n hot-reload** - Built-in file watching and reloading
- ✅ **Better organization** - Clear promotion path from dev to stable
- ✅ **Selective loading** - Easy to disable dev nodes in production
- ✅ **Multiple environments** - Can mount different directories for different deployments

## Risks
- ⚠️ **Low Risk** - Uses native n8n features
- ⚠️ **Directory permissions** - Ensure both paths have correct UID/GID
- ⚠️ **Path references** - Update any hardcoded paths in scripts

## Success Criteria
- [ ] Both `/data/.n8n/stable/` and `/data/.n8n/dev/` directories populated
- [ ] All previous custom nodes still visible in n8n interface
- [ ] Hot-reload working for both stable and dev directories
- [ ] n8n starts successfully and responds with HTTP 200
- [ ] No reduction in total available custom nodes

## Future Enhancements
- Environment-specific loading (production loads only stable)
- Automated testing before promotion from dev to stable
- CI/CD integration for automatic node promotion

## Related Issues
- Built upon Phase 1: Hot-Reload Custom Nodes
- Enables Phase 3: npm Package-Style Loading