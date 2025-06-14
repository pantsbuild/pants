# TypeScript Backend Examples

This directory contains examples demonstrating TypeScript support in Pants with multiple package managers and project structures.

## Project Structure

### projectA (npm + Complex Workspace)
- **Package Manager**: npm
- **Structure**: Complex monorepo with 4 workspace packages
- **Features**: Cross-package dependencies, project references, React components
- **Packages**: common-types, shared-utils, shared-components, main-app

### projectB (yarn + Simple Library)  
- **Package Manager**: yarn@1.22.22
- **Structure**: Simple TypeScript library
- **Features**: Basic library with lodash dependency
- **Config Files**: .npmrc declared as target

### projectC (pnpm + Simple Library)
- **Package Manager**: pnpm@9.15.2  
- **Structure**: Simple TypeScript library
- **Features**: Date utilities with date-fns dependency
- **Config Files**: .pnpmrc declared as target

## Configuration File Management

**Important**: Package manager configuration files must be declared as `file()` targets in BUILD files.

### Required Pattern:
```python
package_json(
    dependencies=[":npmrc", ":pnpmrc"],  # Reference config files
)

file(name="npmrc", source=".npmrc")      # Declare config files
file(name="pnpmrc", source=".pnpmrc")
```

### Supported Config Files:
- `.npmrc` - npm configuration
- `.pnpmrc` - pnpm configuration  
- `pnpm-workspace.yaml` - pnpm workspace definition

### Why This Is Required:
1. **Explicit Dependencies**: Config files affect package installation
2. **Cache Invalidation**: Changes to config files trigger rebuilds
3. **Reproducible Builds**: All inputs are declared and tracked

## Usage Examples

### Check All Projects:
```bash
pants check examples::
```

### Check Individual Projects:
```bash
pants check examples/projectA::    # Complex npm workspace
pants check examples/projectB::    # Simple yarn library  
pants check examples/projectC::    # Simple pnpm library
```

### Check Specific Targets:
```bash
pants check examples/projectA/main-app/src::
pants check examples/projectB/src/index.ts
```

## Package Manager Testing

This examples directory serves as a test suite for package manager compatibility:

- **npm**: Default, works out of the box
- **yarn**: Classic 1.x, standard workspace support  
- **pnpm**: Requires special workspace configuration (see projectA)

Each project demonstrates best practices for that package manager with TypeScript.

## Implementation Status

- ✅ **Target types**: TypeScript and TSX targets work
- ✅ **Dependency inference**: Basic import resolution  
- ✅ **Formatting**: Integration with prettier
- ✅ **Type checking**: Multi-project support with all package managers
- ✅ **Configuration management**: Target-based config file discovery
- ⏳ **Build/compilation**: Future enhancement
- ⏳ **Advanced dependency inference**: Enhanced import resolution