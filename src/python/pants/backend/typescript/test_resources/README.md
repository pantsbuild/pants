# TypeScript Test Resources

This directory contains test project structures for TypeScript backend integration tests. Each project serves different testing purposes and package manager compatibility.

## Project Structure Overview

### 1. `basic_project/` 
**Purpose**: Simple single-package TypeScript project  
**Package Managers**: ✅ npm, ✅ pnpm, ✅ yarn  
**Use Cases**: Basic functionality, success/failure tests, TSX compilation

**Key Features**:
- No workspace dependencies (works with all package managers)
- Includes React/TSX support with proper TypeScript configuration
- Named targets to separate TypeScript and TSX file types
- Suitable for testing core TypeScript compilation features

### 2. `complex_project/`
**Purpose**: Multi-package workspace with cross-dependencies  
**Package Managers**: ✅ npm, ✅ yarn  
**Use Cases**: Workspace dependency resolution, multiple project testing

**Key Features**:
- Multi-package workspace with scoped package dependencies
- TypeScript project references for proper cross-package imports
- Tests workspace dependency resolution capabilities
- Demonstrates complex package manager workspace scenarios

### 3. `pnpm_link/`
**Purpose**: pnpm-specific `link:` protocol testing  
**Package Managers**: ✅ pnpm only  
**Use Cases**: pnpm link protocol validation with hoisted node linking

**Key Features**:
- Tests pnpm's `link:` protocol for local dependencies
- Hoisted node linking configuration for proper module resolution
- Validates that pnpm can resolve workspace packages without TypeScript errors

## Maintenance

### Updating Lockfiles

When dependencies change in package.json files, regenerate lockfiles:

#### Basic Project
```bash
cd test_resources/basic_project

# npm
npm install --package-lock-only

# yarn (use yarn 1.x for compatibility)
npx yarn@1.22.22 install

# pnpm  
pnpm install --lockfile-only
```

#### Complex Project  
```bash
cd test_resources/complex_project

# npm workspace
npm install --package-lock-only

# yarn workspace (use yarn 1.x)
npx yarn@1.22.22 install
```

#### pnpm Link Project
```bash
cd test_resources/pnpm_link

# pnpm with workspace config
pnpm install --lockfile-only
```

### Adding New Dependencies

1. Update the appropriate `package.json` file(s)
2. Regenerate lockfiles using package manager commands (never hand-edit)
3. Update TypeScript imports in test files if needed
4. Run integration tests to verify compatibility
