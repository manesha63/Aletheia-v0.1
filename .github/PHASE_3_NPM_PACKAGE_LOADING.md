# Phase 3: npm Package-Style Custom Node Loading

## Overview
Convert custom nodes to proper npm packages and use n8n's native `LazyPackageDirectoryLoader` for enterprise-grade node management. This provides proper dependency management, versioning, and follows n8n's intended package loading architecture.

**Priority**: Low  
**Difficulty**: Medium  
**Estimated Time**: 1-2 days  
**Impact**: Production-grade architecture  
**Depends on**: Phase 2 (Multi-Path Node Loading)

## Current Problem
- Custom nodes loaded as loose files - no dependency management
- No version control for individual nodes
- Manual TypeScript compilation and build process
- Not using n8n's intended package loading mechanism

## Solution
Convert custom nodes to proper npm packages that can be installed and managed through n8n's native package loading system.

## n8n Source Code Reference
**From investigation of n8n 1.99.1 source**:
- File: `/usr/local/lib/node_modules/n8n/dist/load-nodes-and-credentials.js`
- Class: `LazyPackageDirectoryLoader` - n8n's native package loader
- Method: `loadNodesFromNodeModules()` - scans for `n8n-nodes-*` packages
- Pattern: Loads from `node_modules/n8n-nodes-*/` with proper package.json

## Architecture Changes

### Current Architecture
```
n8n/stable-nodes/
├── n8n-nodes-haystack/
│   ├── dist/nodes/HaystackSearch/HaystackSearch.node.js
│   └── package.json
```

### Target Architecture
```
n8n/packages/
├── n8n-nodes-haystack/
│   ├── package.json           # Proper npm package
│   ├── dist/                 # Built files
│   ├── src/                  # TypeScript source
│   ├── .npmignore
│   └── README.md
```

## Files to Create/Modify

### 1. Package Structure Enhancement

For each custom node, enhance `package.json`:

**Current** (example from haystack):
```json
{
  "name": "n8n-nodes-haystack",
  "version": "2.0.0",
  "main": "index.js",
  "n8n": {
    "n8nNodesApiVersion": 1,
    "nodes": [
      "dist/nodes/HaystackSearch/HaystackSearch.node.js"
    ]
  }
}
```

**Enhanced** (proper npm package):
```json
{
  "name": "n8n-nodes-haystack",
  "version": "2.0.0",
  "description": "RAG-focused n8n node for Haystack and Elasticsearch integration",
  "main": "dist/index.js",
  "files": [
    "dist/**/*"
  ],
  "scripts": {
    "build": "tsc && gulp build:icons",
    "dev": "tsc --watch",
    "prepack": "npm run build"
  },
  "n8n": {
    "n8nNodesApiVersion": 1,
    "nodes": [
      "dist/nodes/HaystackSearch/HaystackSearch.node.js"
    ]
  },
  "peerDependencies": {
    "n8n-workflow": "*"
  },
  "engines": {
    "node": ">=18"
  }
}
```

### 2. `Dockerfile.n8n` ⚠️ **MAJOR CHANGES**
**Location**: `/Dockerfile.n8n`

**Current** (copy and build approach):
```dockerfile
# Copy custom nodes directly to node_modules
COPY ./n8n/custom-nodes/n8n-nodes-haystack /usr/local/lib/node_modules/n8n-nodes-haystack
# Build them individually
RUN for node_dir in /usr/local/lib/node_modules/n8n-nodes-*; do ...
```

**New** (proper npm installation):
```dockerfile
# Create package directory
WORKDIR /tmp/packages

# Copy package files
COPY ./n8n/packages/n8n-nodes-haystack ./n8n-nodes-haystack
COPY ./n8n/packages/n8n-nodes-deepseek ./n8n-nodes-deepseek

# Install packages properly
RUN npm install --global ./n8n-nodes-haystack ./n8n-nodes-deepseek ./n8n-nodes-citationchecker

# Clean up
RUN rm -rf /tmp/packages
```

### 3. `docker-compose.yml` ⚠️ **SIMPLIFICATION**
**Location**: `/docker-compose.yml`

**Current** (volume mounts):
```yaml
volumes:
  - ./n8n/stable-nodes:/data/.n8n/stable:ro
  - ./n8n/dev-nodes:/data/.n8n/dev:ro
environment:
  - N8N_CUSTOM_EXTENSIONS=/data/.n8n/stable;/data/.n8n/dev
```

**New** (npm packages + dev mounts):
```yaml
volumes:
  # Only mount dev nodes for development
  - ./n8n/dev-packages:/data/.n8n/dev:ro
environment:
  # Stable nodes installed as packages, dev nodes mounted
  - N8N_CUSTOM_EXTENSIONS=/data/.n8n/dev
```

### 4. Development Scripts

Create `scripts/build-packages.sh`:
```bash
#!/bin/bash
# Build all custom node packages

for package_dir in n8n/packages/*/; do
    if [ -d "$package_dir" ]; then
        echo "Building $(basename "$package_dir")..."
        (cd "$package_dir" && npm install && npm run build)
    fi
done
```

Create `scripts/install-packages.sh`:
```bash
#!/bin/bash
# Install packages for local development

for package_dir in n8n/packages/*/; do
    if [ -d "$package_dir" ]; then
        package_name=$(basename "$package_dir")
        echo "Installing $package_name..."
        npm install --global "$package_dir"
    fi
done
```

## Files to Review
- All existing custom node `package.json` files - enhance for proper npm packaging
- Build scripts - update for new package structure
- Development workflow documentation

## Migration Steps

### 1. Restructure Existing Nodes
```bash
# Create package directories
mkdir -p n8n/packages n8n/dev-packages

# Move stable nodes to packages
mv n8n/stable-nodes/n8n-nodes-haystack n8n/packages/
mv n8n/stable-nodes/n8n-nodes-deepseek n8n/packages/
mv n8n/stable-nodes/n8n-nodes-citationchecker n8n/packages/

# Keep dev nodes in dev-packages for volume mounting
mv n8n/dev-nodes/* n8n/dev-packages/
```

### 2. Enhance Package Files
For each package in `n8n/packages/`, update:
- `package.json` - Add proper npm fields
- Create `.npmignore` - Exclude source files from package
- Verify `dist/` structure matches n8n expectations

### 3. Update Docker Build
- Modify `Dockerfile.n8n` to use npm install
- Update `docker-compose.yml` for new structure
- Test build process

### 4. Create Development Workflow
- Build scripts for packages
- Installation scripts for development
- Documentation for package management

## Testing Strategy

### 1. Package Building
```bash
# Test each package builds correctly
cd n8n/packages/n8n-nodes-haystack
npm run build
npm pack  # Test packaging
```

### 2. Installation Testing
```bash
# Test global installation
npm install --global ./n8n/packages/n8n-nodes-haystack

# Verify installation
npm list -g n8n-nodes-haystack
```

### 3. n8n Integration
```bash
# Build new Docker image
docker-compose build n8n

# Start and test
docker-compose up -d n8n
curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/
```

### 4. Development Workflow
```bash
# Test dev package hot-reload still works
echo "// test change" >> n8n/dev-packages/n8n-nodes-citation-gen/dist/index.js
```

## Expected Benefits
- ✅ **Proper dependency management** - npm handles dependencies
- ✅ **Version control** - Each node has proper versioning
- ✅ **Standard workflow** - Uses npm ecosystem tools
- ✅ **Better distribution** - Can publish to npm registry
- ✅ **Native n8n support** - Uses intended package loading mechanism
- ✅ **Enterprise ready** - Production-grade architecture

## Risks
- ⚠️ **Medium Risk** - Significant architectural change
- ⚠️ **Build complexity** - More complex build process
- ⚠️ **Development workflow** - Changes how developers work with nodes
- ⚠️ **Testing required** - Need extensive testing of package installation

## Success Criteria
- [ ] All stable nodes converted to proper npm packages
- [ ] Docker build successfully installs packages
- [ ] All custom nodes still appear in n8n interface
- [ ] Development workflow maintained for dev packages
- [ ] Package versioning working correctly
- [ ] Hot-reload still functional for dev packages

## Future Enhancements
- CI/CD pipeline for automatic package building
- npm registry publication for sharing nodes
- Automated testing for each package
- Package dependency management
- Semantic versioning automation

## Rollback Plan
If issues occur:
1. Revert to Phase 2 structure (stable-nodes, dev-nodes)
2. Use volume mounts instead of npm installation
3. Keep current runtime copying as fallback

## Related Issues
- Builds upon Phase 2: Multi-Path Node Loading
- Addresses enterprise deployment requirements
- Enables proper dependency management
- Facilitates node sharing and distribution