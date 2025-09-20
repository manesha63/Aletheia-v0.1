# Archived Custom Nodes

This directory contains custom nodes that have been removed from active use due to issues.

## n8n-nodes-bitnet

**Date Archived**: September 12, 2025
**Reason**: Dependency compilation issues causing n8n startup failures
**Issue**: Missing `bitnet-server-wrapper.js` file during Docker build process
**Status**: Can be restored once dependency issues are resolved

The BitNet node has functionality for AI processing with summary capabilities but requires:
1. Proper compilation of `bitnet-server-wrapper.js`
2. Fix for module path resolution in dist folder
3. Testing to ensure no other dependency conflicts