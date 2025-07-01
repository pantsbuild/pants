# TypeScript Backend

## Setup

Enable in `pants.toml`:
```toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.experimental.typescript"
]
```

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
- Output directory caching (configurable via `[typescript].output_dirs`)

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
- No workspace package resolution yet (relies on package manager symlinks for type checking)

## Package Managers

All major package managers supported with workspace configurations:

- **npm**: Standard `workspaces` field
- **pnpm**: Requires `link:` dependencies + hoisting config  
- **yarn**: Works out-of-box with Yarn Classic (1.x)

## Configuration

### TypeScript Options
```toml
[typescript]  
version = "typescript@5.8.2"      # Tool version
output_dirs = ["dist", "build"]   # Override output directory patterns
install_from_resolve = "frontend" # Use specific resolve
```

### Package Manager Selection
```bash
pants --nodejs-package-manager=pnpm check ::
```

## Architecture

Type checking operates at **project level** using TypeScript's `--build` mode:
- Discovers projects via JavaScript backend integration
- Groups targets by containing NodeJS project  
- Executes concurrent project-level type checking
- Caches compilation artifacts for performance

## Known Limitations

- No file-level skip functionality (use TypeScript native `// @ts-ignore`)
- Requires proper workspace configuration for cross-package imports
- pnpm requires special hoisting configuration for workspace resolution
