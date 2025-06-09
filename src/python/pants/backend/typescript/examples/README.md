# TypeScript Monorepo Example

This directory contains a comprehensive TypeScript monorepo example that demonstrates how to structure projects for the Pants TypeScript backend, including support for future typechecking capabilities.

## Project Structure

This example models a typical TypeScript monorepo with:

- **Root workspace**: Package manager workspace configuration
- **Main application** (`main-app/`): A web application that depends on shared libraries
- **Shared utilities** (`shared-utils/`): Common utility functions
- **Shared components** (`shared-components/`): Reusable UI components
- **Common types** (`common-types/`): Shared TypeScript type definitions

## Package Structure

```
examples/
├── README.md                    # This file
├── BUILD                        # Root workspace
├── package.json                 # Root workspace configuration
├── pnpm-workspace.yaml         # PNPM workspace definition
├── pnpm-lock.yaml              # Package manager lockfile
├── common-types/               # Shared type definitions
│   ├── BUILD
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── BUILD
│       ├── index.ts
│       └── api.ts
├── shared-utils/               # Shared utility functions
│   ├── BUILD
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── BUILD
│       ├── index.ts
│       ├── math.ts
│       └── test/
│           ├── BUILD
│           └── math.test.ts
├── shared-components/          # Reusable UI components
│   ├── BUILD
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── BUILD
│       ├── index.ts
│       ├── Button.tsx
│       └── test/
│           ├── BUILD
│           └── Button.test.tsx
└── main-app/                   # Main application
    ├── BUILD
    ├── package.json
    ├── tsconfig.json
    └── src/
        ├── BUILD
        ├── index.ts
        ├── App.tsx
        └── test/
            ├── BUILD
            └── App.test.tsx
```

## Current Pants Goals

### Formatting
```bash
# Format all TypeScript files in the monorepo
pants fmt examples::

# Format specific packages
pants fmt examples/shared-utils::
pants fmt examples/main-app::
```

### Linting  
```bash
# Lint all TypeScript files (when prettier is configured)
pants lint examples::

# Lint specific packages
pants lint examples/shared-utils::
```

### Testing
```bash
# Run all tests in the monorepo
pants test examples::

# Run tests for specific packages
pants test examples/shared-utils::
pants test examples/main-app::

# Run a specific test file
pants test examples/shared-utils/src/test/math.test.ts
```

### Dependency Analysis
```bash
# Show dependencies for a target
pants dependencies examples/main-app/src:index

# Show dependents of a target
pants dependents examples/common-types/src:index

# List all targets
pants list examples::
```

## Future Typechecking Goals

Once TypeScript typechecking is implemented, these commands will be available:

### Type Checking
```bash
# Type check all TypeScript files (follows project reference order)
pants check examples::

# Type check specific packages (dependencies checked first)
pants check examples/shared-utils::
pants check examples/main-app::

# Build references (incremental compilation)
tsc --build examples/

# Type check with specific TypeScript version
pants --tsc-version=typescript@5.8.2 check examples::
```

### Build/Compilation
```bash
# Compile TypeScript to JavaScript (future goal)
pants package examples/main-app::

# Build specific packages
pants package examples/shared-components::
```

## Key Features Demonstrated

### 1. Workspace Configuration
- PNPM workspace setup with `pnpm-workspace.yaml`
- Shared lockfile for dependency management
- Proper package manager configuration

### 2. TypeScript Configuration
- **Project References**: Root `tsconfig.json` with references to all packages
- **Composite builds**: Each package is a TypeScript composite project
- **Incremental compilation**: Enabled for fast rebuilds
- **Dependency order**: TypeScript understands build dependencies
- **Declaration files**: Generated for all packages for cross-package type checking

### 3. Package Dependencies
- Internal dependencies between workspace packages
- External npm dependencies
- Development dependencies for testing

### 4. Target Structure
- `typescript_sources()` for source files
- `typescript_tests()` for test files  
- `tsx_sources()` for React components
- `package_json()` targets with proper configuration

### 5. Dependency Inference
- Automatic discovery of internal dependencies
- TypeScript import resolution
- Package.json dependency detection

## Testing the Example

To test this example structure:

1. **Enable the TypeScript backend** in your `pants.toml`:
   ```toml
   [GLOBAL]
   backend_packages = [
       "pants.backend.experimental.typescript",
       "pants.backend.experimental.tsx",
   ]
   ```

2. **Run tailor** to verify target generation:
   ```bash
   pants tailor examples::
   ```

3. **Test dependency inference**:
   ```bash
   pants dependencies examples/main-app/src:index
   ```

4. **Run formatting**:
   ```bash
   pants fmt examples::
   ```

5. **Run tests** (when test framework is configured):
   ```bash
   pants test examples::
   ```

## Configuration Notes

### Package Manager
This example uses PNPM but can be adapted for npm or yarn by:
- Replacing `pnpm-workspace.yaml` with `workspaces` field in root `package.json`
- Updating lockfile name (`package-lock.json` for npm, `yarn.lock` for yarn)

### TypeScript Versions
Each package can specify its own TypeScript version in `devDependencies`, or rely on the workspace root version.

### Testing Framework
The example includes Jest configuration but can be adapted for other test runners like Vitest or Mocha.

## TypeScript Project References Integration

This example uses [TypeScript Project References](https://www.typescriptlang.org/docs/handbook/project-references.html) which provides several benefits:

### **How Project References Work Here**

**Root Configuration** (`tsconfig.json`):
```json
{
  "files": [],
  "references": [
    { "path": "./common-types" },
    { "path": "./shared-utils" },
    { "path": "./shared-components" },
    { "path": "./main-app" }
  ]
}
```

**Package Configuration** (e.g., `main-app/tsconfig.json`):
```json
{
  "compilerOptions": {
    "composite": true,      // Enables project references
    "incremental": true,    // Faster rebuilds
    "declaration": true     // Generates .d.ts files
  },
  "references": [
    { "path": "../common-types" },
    { "path": "../shared-utils" },
    { "path": "../shared-components" }
  ]
}
```

### **Benefits for Pants TypeScript Backend**

1. **Incremental Type Checking**: Only recheck changed projects and their dependents
2. **Build Ordering**: TypeScript knows to check dependencies first
3. **Better IDE Performance**: VS Code can load projects individually
4. **Declaration File Generation**: Enables proper cross-package type checking
5. **Pants Compatibility**: Aligns with Pants' understanding of dependencies

### **How Pants Will Leverage This**

- **Dependency Graph**: Pants can read `references` to understand project dependencies
- **Incremental Builds**: Use TypeScript's incremental compilation for speed
- **Parallel Execution**: Check independent packages in parallel
- **Target Ordering**: Ensure dependencies are type-checked before dependents

### **Commands for Project References**

```bash
# Build all projects in dependency order
tsc --build examples/

# Clean all build outputs
tsc --build examples/ --clean

# Force rebuild all projects
tsc --build examples/ --force

# Verbose output showing what's being built
tsc --build examples/ --verbose
```

## Implementation Status

- ✅ **Target types**: TypeScript and TSX targets work
- ✅ **Dependency inference**: Basic import resolution  
- ✅ **Formatting**: Integration with prettier
- ✅ **Project References**: Configured for optimal TypeScript experience
- ⏳ **Type checking**: In development (tsc integration)
- ⏳ **Build/compilation**: Future enhancement
- ⏳ **Advanced dependency inference**: Enhanced import resolution