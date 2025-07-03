# TypeScript Download-and-Execute Investigation

## Issue Summary

**Problem**: TypeScript check tests failing with "Cannot find module 'react'" errors in `basic_project` test resources.

**Root Cause**: TypeScript was removed from `basic_project/package.json` during Phase 8 to test download-and-execute path, but TSX components require React dependencies that download-and-execute cannot provide.

## Technical Background

### Execution Paths in NodeJSToolBase
- **Download-and-execute**: `install_from_resolve = None` → uses `pnpm dlx`, `npm exec`, `yarn dlx`
- **Resolve-based**: `install_from_resolve = "resolve_name"` → installs from lockfile + executes

### The Fundamental Problem
Download-and-execute only downloads the tool (TypeScript), not project dependencies (React, @types/react). TypeScript needs both:
1. TypeScript compiler (✅ provided by download-and-execute)
2. Type definitions for dependencies (❌ NOT provided)

### Key Files
- `/src/python/pants/backend/javascript/subsystems/nodejs_tool.py` - Tool execution logic
- `/src/python/pants/backend/javascript/package_manager.py` - Command templates
- `/src/python/pants/backend/typescript/check.py` - TypeScript check implementation
- `/src/python/pants/backend/typescript/test_resources/basic_project/` - Failing test resources

## Investigation Results

### Other Tools Analysis
- **Prettier**: Works with download-and-execute (no external dependencies needed)
- **OpenAPI Format**: Works with download-and-execute (standalone tool)
- **TypeScript**: Fails with download-and-execute (needs project dependencies)

### Proposed Solutions Considered

1. **Two-sandbox approach**: Install dependencies in sandbox 1, merge with tool execution in sandbox 2
   - **Complexity**: High (lockfile exclusion, digest merging)
   - **Performance**: Additional dependency installation overhead

2. **Multi-package download**: Extend package managers to download tool + dependencies
   - **Complexity**: Medium (version resolution, package manager support)
   - **Compatibility**: Varies by package manager

3. **Hybrid approach**: Install dependencies + download tool separately
   - **Complexity**: Medium (not truly download-and-execute)

## Decision

**TypeScript only supports resolve-based execution.**

**Rationale**:
- Real-world TypeScript projects have `typescript` in `package.json`
- Download-and-execute is incompatible with dependency-requiring tools
- Error messages would be confusing (which package.json? which resolve?)
- Resolve-based execution covers all real-world usage

## Next Steps

1. **Fix Tests**: Add TypeScript back to test resources or use dependency-free components
2. **Document Limitation**: Update documentation that TypeScript requires resolve-based execution
3. **Update Phase 8 Status**: Reflect that download-and-execute path is not applicable to TypeScript

## Why Error Messages Won't Work

### `install_from_resolve` Configuration Issues
- Users need to know resolve names (internal Pants concept)
- Multi-project workspaces have complex resolve mappings
- Configuration is not user-friendly

### Package.json Location Issues  
- Monorepos: Which package.json should contain TypeScript?
- Resolve system automatically maps targets to projects
- Adding to wrong package.json won't help

### Test Fix Options
- **Option A**: Add TypeScript back to `basic_project/package.json`
- **Option B**: Replace React TSX with dependency-free TypeScript code
- **Option C**: Split test resources (dependency-free vs with-dependencies)

## Historical Context

This investigation stems from Phase 8 work where download-and-execute path was fixed for package manager command templates, but revealed the fundamental incompatibility between download-and-execute and dependency-requiring tools like TypeScript.

**Key insight**: Download-and-execute works for standalone tools but not for tools that need project dependencies.