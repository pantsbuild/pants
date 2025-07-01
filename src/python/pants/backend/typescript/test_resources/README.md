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

## Test Usage Patterns

### Basic Project Tests (All Package Managers)
```python
def test_basic_functionality(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    rule_runner, project_type, package_manager = basic_rule_runner
    test_files = _load_project_test_files(project_type)
    # Tests: basic_project with npm/pnpm/yarn
```

### Workspace Tests (npm/yarn only)  
```python
def test_workspace_features(workspace_rule_runner: tuple[RuleRunner, str, str]) -> None:
    rule_runner, project_type, package_manager = workspace_rule_runner
    test_files = _load_project_test_files(project_type)
    # Tests: complex_project with npm/yarn only
```

### pnpm-specific Tests
```python
def test_pnpm_features(pnpm_rule_runner: tuple[RuleRunner, str, str]) -> None:
    rule_runner, project_type, package_manager = pnpm_rule_runner
    test_files = _load_project_test_files(project_type)
    # Tests: pnpm_link with pnpm only
```

## Manual Testing

### Test TypeScript Compilation
```bash
# Test basic project with different package managers
cd test_resources/basic_project
./pants check src/
./pants --nodejs-package-manager=npm check src/
./pants --nodejs-package-manager=yarn check src/  
./pants --nodejs-package-manager=pnpm check src/

# Test TSX compilation
./pants check src/Button.tsx

# Test complex workspace (npm/yarn only)
cd test_resources/complex_project  
./pants --nodejs-package-manager=npm check ::
./pants --nodejs-package-manager=yarn check ::

# Test pnpm link protocol
cd test_resources/pnpm_link
./pants --nodejs-package-manager=pnpm check src/
```

### Test Cross-Package Imports
```bash
# Complex project - test workspace dependency resolution
cd test_resources/complex_project
./pants --nodejs-package-manager=npm check main-app/src/
./pants --nodejs-package-manager=yarn check shared-utils/src/

# Should resolve @test/shared-utils and @test/common-types imports
```

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

### Package Manager Compatibility Notes

- **npm**: Works with all project structures
- **yarn**: Works with basic and complex projects (use yarn 1.x lockfiles)  
- **pnpm**: Works with basic and pnpm_link projects; complex workspace needs additional configuration
