# TypeScript Backend

## Limitations

### Install without resolve / Install from different resolve

PR_NOTE: Needs discussion. These options currently aren't supported. 

While NodeJSTool supports standalone tool installation, typescript needs dependencies (e.g. 3rd-party types) to work.
I can't think of a real-world scenario where this would be required. 

If you do attempt to run typechecking in a project without typescript installed, package manager error will be along the lines of
`tsc not found`. We could wrap this error potentially, but don't it's worthwhile at this point.

## Features

### Type Checking
```bash
pants check ::           # Check all TypeScript projects  
pants check src/app::    # Check specific project
```

**Supported**:
- Multi-project concurrent type checking
- Incremental compilation via `.tsbuildinfo` caching  
- Workspace package resolution (npm, pnpm, yarn)
- Project references and complex `tsconfig.json` configurations
- Automatic output directory detection from `tsconfig.json` outDir settings

### Target Generation  
```bash
pants tailor ::
```
Generates `typescript_sources()`, `typescript_tests()`, and `tsx_sources()` targets.

### Dependency Inference

**Implementation**: TypeScript/TSX files use the same dependency inference as JavaScript files via unified tree-sitter TSX parser in the JavaScript backend.

**Supported Import Patterns**:
```typescript
// ES Modules
import utils from "./utils";               // → utils.ts
import { Button } from "../components";    // → components/index.ts
import * as lib from "library";           // → package.json dependency

// TypeScript-specific  
import type { User } from "./types";      // → types.ts (treated as regular dependency)
export type { Config } from "./config";  // → config.ts

// Dynamic imports
const module = await import("./module");  // → module.ts

// CommonJS (legacy)
const fs = require("fs");                 // → Node.js built-in
```

**Package Resolution**:
- npm/yarn/pnpm packages from `package.json` dependencies
- TypeScript `compilerOptions.paths` mapping (e.g., `"@/*": ["./src/*"]`)
- Node.js subpath imports via `package.json` `imports` field
- Scoped packages and subpaths (`@mui/material/Button`)

**Current Limitations**:
- Type-only imports treated as regular dependencies (no impact on type checking)
- Dynamic require with variables ignored (`require(variable)`)

## Package Managers

All major package managers supported with workspace configurations:

- **npm**: Standard `workspaces` field in root package.json
- **pnpm**: Requires `link:` protocol dependencies + `pnpm-workspace.yaml`  
- **yarn**: Works out-of-box with Yarn Classic (1.x)

### pnpm Workspace Setup

pnpm requires special configuration for cross-package imports in TypeScript:

For example, to migrate an existing npm/yarn workspace to pnpm:

1. **Create `pnpm-workspace.yaml`**:
   ```yaml
   packages:
     - 'packages/*'  # or list explicit package directories
   ```

2. **Update workspace dependencies** in package.json files:
   ```json
   // Before (npm/yarn)
   {
     "dependencies": {
       "@myorg/shared": "workspace:*"
     }
   }
   
   // After (pnpm for TypeScript)
   {
     "dependencies": {
       "@myorg/shared": "link:../shared"
     }
   }
   ```

3. **Regenerate lockfile**:
   ```bash
   rm pnpm-lock.yaml
   pnpm install
   ```

The `link:` protocol creates symlinks that TypeScript can resolve for cross-package imports, enabling proper type checking across workspace packages.

## Architecture

Type checking operates at **project level** using TypeScript's `--build` mode:

### Why Project-Level with `--build` Mode

TypeScript compilation operates at the **NodeJS project level** using `--build` mode and project references, which is the modern TypeScript compilation approach:

1. **Cross-package imports**: Workspace packages import from each other (`@myorg/shared`)
2. **Shared configuration**: Single root `tsconfig.json` coordinates all sub-projects
3. **Dependency resolution**: Package manager resolves all workspace dependencies together
4. **Incremental compilation**: TypeScript's `.tsbuildinfo` tracks project-wide incremental state
5. **Modern architecture**: `--build` + project references is TypeScript's recommended approach for monorepos

**Why `--build` + Project References (Modern)**:
```json
// Root tsconfig.json coordinates sub-projects
{
  "references": [
    { "path": "./packages/shared" },
    { "path": "./packages/app" }
  ]
}

// Individual packages use "composite": true
{
  "compilerOptions": { "composite": true },
  "references": [{ "path": "../shared" }]
}
```

**Per-package compilation doesn't work** because:
- TypeScript needs full workspace context for cross-package imports
- Project references enable proper dependency ordering and caching
- `--build` mode provides optimal incremental compilation across the entire project graph

### Implementation Details

- **Project Discovery**: Integrates with JavaScript backend's NodeJS project resolution
- **Target Grouping**: Groups Pants targets by containing NodeJS project  
- **Concurrent Execution**: Multiple projects type-checked in parallel
- **Artifact Caching**: Caches `.tsbuildinfo` and output files for incremental compilation
- **Configuration Respect**: Uses project's `tsconfig.json` and package manager setup

## Process Flow

The TypeScript backend follows a multi-stage process that separates package management from compilation:

### 1. **Package Resolution Stage** (JavaScript Backend)
   - **Trigger**: When a `package_json` target is encountered
   - **Process**: Runs `npm/pnpm/yarn install` to resolve dependencies
   - **Inputs**: 
     - `package.json` files
     - Lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`)
     - Package manager config files (`.npmrc`, `.pnpmrc`, `pnpm-workspace.yaml`)
   - **Outputs**: 
     - Populated `node_modules` directory
     - Updated lockfile (if dependencies changed)
   - **Caching**: Results are heavily cached based on input digest

### 2. **TypeScript Compilation Stage** (TypeScript Backend)
   - **Trigger**: When `pants check` is run on TypeScript targets
   - **Process**: Runs `tsc --build` for type checking
   - **Inputs**:
     - TypeScript source files (`.ts`, `.tsx`)
     - `tsconfig.json` files
     - Pre-resolved `node_modules` from stage 1
     - Cached `.tsbuildinfo` files (for incremental compilation)
     - File targets declared as dependencies
   - **Outputs**:
     - Exit code (0 for success, non-zero for type errors)
     - `.tsbuildinfo` files (incremental compilation state)
     - Compiled JavaScript files (if `emitDeclarationOnly` is false)
     - Declaration files (`.d.ts`)
   - **Caching**: TypeScript artifacts are cached and restored for incremental builds

### 4. **Configuration Files and Dependencies**

For proper cache invalidation, configuration files must be declared as explicit file targets:

```python
# BUILD file
package_json()

# Declare package manager config files as file targets
file(name="npmrc", source=".npmrc")
file(name="pnpmrc", source=".pnpmrc") 

# TypeScript targets can depend on these
typescript_sources(
    dependencies=[":npmrc"],  # If TypeScript needs specific registry config
)
```

**Note**: While the TypeScript backend includes file targets in its dependency collection, changes to package manager config files (`.npmrc`, `.pnpmrc`) primarily affect the package resolution stage, not the TypeScript compilation output itself.

  