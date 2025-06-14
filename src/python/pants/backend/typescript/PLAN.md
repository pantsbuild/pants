# TypeScript Backend Typechecking Implementation Plan

## Overview

This document outlines the plan for implementing TypeScript typechecking support in the Pants TypeScript backend. The goal is to add `pants check` functionality that integrates with the TypeScript compiler (`tsc`) to provide type checking for TypeScript projects.

## Current State

- ✅ **Target types**: `typescript_sources`, `tsx_sources`, `typescript_tests`, `tsx_tests`
- ✅ **Basic dependency inference**: Import statement analysis, package.json dependencies
- ✅ **Formatting**: Integration with prettier
- ✅ **File discovery**: Target generation and glob patterns
- ✅ **TypeScript configuration**: Comprehensive `tsconfig.json` parsing with extends support (`pants.backend.typescript.tsconfig`)
- ❌ **Type checking**: Not implemented (this plan's focus)

## Goals

### Primary Goal
Implement `pants check examples/main-app::` that runs TypeScript type checking using `tsc --noEmit`.

### Success Criteria
1. Type errors are detected and reported with proper file paths and line numbers
2. Cross-package dependencies are resolved correctly (workspace imports)
3. Integration respects TypeScript configuration (`tsconfig.json`)
4. Performance is reasonable for large codebases
5. Works with existing JavaScript backend patterns

## Implementation Plan

### Phase 1: Core TypeScript Tool Integration

**Goal**: Basic `tsc` execution for single packages

**Tasks**:
1. **Create TypeScript tool subsystem** (`typescript_tool.py`)
   - Extend `NodeJSToolBase` (following prettier/eslint patterns)
   - Default to `typescript@5.8.2`
   - Support `--tsc-version` option
   - Handle binary name override (`package=typescript`, `binary=tsc`)

2. **Implement TypeScript check rule** (`check.py`)
   - Create `TypeScriptCheckRequest` and `TypeScriptCheckResult`
   - Process TypeScript source targets
   - Execute `tsc --noEmit` with proper working directory
   - Parse and format error output

3. **Add check goal integration**
   - Register TypeScript check rule with `UnionRule(CheckRequest, TypeScriptCheckRequest)`
   - Follow existing patterns from `pants.backend.terraform.goals.check` (modern, uses call-by-name)

4. **IDE integration (VSCode target)**
   - Preserve existing `tsconfig.json` and `package.json` files for VSCode language server
   - Ensure declaration files (`.d.ts`) are generated in expected locations
   - Don't interfere with `node_modules` structure that VSCode relies on
   - Maintain file paths that VSCode can resolve for go-to-definition and IntelliSense

5. **Configuration integration**
   - Leverage existing tsconfig.json parsing (`pants.backend.typescript.tsconfig`)
   - Use parsed configuration for compiler options in type checking
   - Support `--tsc-args` for custom compiler flags
   - Ensure consistent TypeScript version across resolve (required for project references)

6. **Basic incremental compilation (single package)**
   - Use `tsc --build` for individual packages with project references
   - Cache `.tsbuildinfo` files between runs for single package
   - Optimize for repeated executions on same package

**Acceptance Criteria**:
- `pants check examples/common-types::` works for single package
- Type errors are properly reported with file paths
- TypeScript configuration is fully respected
- IDE integration works seamlessly
- Custom configuration scenarios are supported
- Subsequent runs on same package are faster due to incremental compilation

### Phase 1.5: Hardcoded Workspace Support (COMPLETED)

**Status**: ✅ Completed with npm package manager support

### Phase 1.6: pnpm Package Manager Support (COMPLETED)

**Goal**: ✅ Investigate and fix TypeScript check compatibility with pnpm package manager

**Status**: ✅ **COMPLETED** - TypeScript check now works with pnpm workspace packages

**Key Challenge Solved**: pnpm creates workspace symlinks in individual package `node_modules` directories, but Pants' digest merging process only preserves the root-level `node_modules`, losing the workspace symlinks needed for TypeScript module resolution.

**Root Cause Identified**:
- pnpm correctly creates workspace symlinks: `shared-utils/node_modules/@pants-example/common-types -> ../../../common-types`
- Pants digest merging preserves only the root `node_modules`, losing individual package-level directories
- TypeScript execution fails because workspace symlinks are missing in the execution sandbox

**Solution Implemented**:
Based on [pnpm issue #3642](https://github.com/pnpm/pnpm/issues/3642), the solution is to force workspace packages to be hoisted to the root level by:

1. **Add workspace packages as explicit dependencies in root `package.json` using `link:` protocol**:
   ```json
   {
     "dependencies": {
       "@pants-example/common-types": "link:common-types",
       "@pants-example/shared-utils": "link:shared-utils", 
       "@pants-example/shared-components": "link:shared-components",
       "@pants-example/main-app": "link:main-app"
     }
   }
   ```

2. **Configure pnpm workspace hoisting in `pnpm-workspace.yaml`**:
   ```yaml
   packages:
     - 'common-types'
     - 'shared-utils'  
     - 'shared-components'
     - 'main-app'
   nodeLinker: hoisted
   publicHoistPattern:
     - "*"
   ```

**Key Configuration Notes**:
- `nodeLinker: hoisted` forces pnpm to use hoisted mode instead of symlink mode
- `publicHoistPattern: ["*"]` hoists all packages to root level (sufficient for most cases)
- `hoistWorkspacePackages: true` only enables hoisting of external (non-workspace) dependencies used by workspace packages — NOT the workspace packages themselves
- The `link:` protocol in dependencies is essential to force root-level symlinks that survive digest merging

**Package Manager Configuration Differences**:

| Package Manager | Workspace Configuration Required |
|-----------------|----------------------------------|
| **npm** | Works out of the box with `workspaces` field in package.json |
| **pnpm** | Requires `link:` dependencies + hoisting configuration in pnpm-workspace.yaml |
| **yarn** | TBD (Phase 1.7) |

**Verification**:
- ✅ `pants check examples::` works with `--nodejs-package-manager=pnpm`
- ✅ Workspace package imports resolve correctly (`@pants-example/common-types` etc.)
- ✅ No module resolution errors for workspace packages
- ✅ Root-level symlinks preserved: `node_modules/@pants-example/common-types -> ../../common-types`
- ✅ Performance is comparable to npm

**Investigation Methods That Led to Solution**:
1. ✅ Manual sandbox inspection revealed symlinks exist but in wrong locations
2. ✅ Identified digest merging preserves only root `node_modules`
3. ✅ Research on pnpm workspace hoisting via GitHub issues
4. ✅ Testing `link:` protocol + hoisting configuration combination

### Phase 1.7: yarn Package Manager Support (COMPLETED)

**Goal**: ✅ Investigate and fix TypeScript check compatibility with yarn package manager

**Status**: ✅ **COMPLETED** - TypeScript check works with Yarn Classic workspace packages

**Research Findings - Yarn Version Compatibility**:

**Yarn Classic (1.x) vs Yarn Berry (2.x+)**:
- **Yarn Classic (1.22.22)**: Traditional `node_modules`, uses `--frozen-lockfile`, wide ecosystem compatibility
- **Yarn Berry (2.x+)**: Complete rewrite with Plug'n'Play (PnP), uses `--immutable`, performance improvements

**Pants Support Analysis**:
- **Current Default**: Yarn 1.22.22 (Classic) - optimal for compatibility
- **Automatic Version Detection**: Pants auto-detects version and uses appropriate flags
- **Berry Compatibility**: Requires `nodeLinker: node-modules` in `.yarnrc.yml` for Pants compatibility
- **PnP Mode**: Not compatible with Pants' current digest merging architecture

**Solution Implemented**:
Yarn Classic works perfectly with standard workspace configuration - **no special configuration required**!

1. **Standard workspace dependencies** using version wildcards:
   ```json
   {
     "dependencies": {
       "@pants-example/common-types": "*",
       "@pants-example/shared-components": "*"
     }
   }
   ```

2. **Root workspace configuration**:
   ```json
   {
     "workspaces": [
       "common-types",
       "shared-utils", 
       "shared-components",
       "main-app"
     ]
   }
   ```

**Key Advantages of Yarn Classic**:
- ✅ Creates root-level workspace symlinks automatically
- ✅ No need for `link:` protocol dependencies (unlike pnpm)
- ✅ No special hoisting configuration required
- ✅ Fully compatible with Pants' digest merging process
- ✅ Already the default in Pants (yarn@1.22.22)

**Verification Results**:
- ✅ `pants check examples::` works with `--nodejs-package-manager=yarn`
- ✅ Workspace package imports resolve correctly (`@pants-example/common-types` etc.)
- ✅ Root-level symlinks preserved: `node_modules/@pants-example/common-types -> ../../common-types`
- ✅ No module resolution errors for workspace packages
- ✅ Performance comparable to npm
- ✅ TypeScript errors are only about testing library issues, not workspace resolution

**Package Manager Configuration Matrix** (Updated):

| Package Manager | Workspace Configuration Required | Status | Notes |
|-----------------|----------------------------------|--------|-------|
| **npm** | Standard `workspaces` field in package.json | ✅ Working | Works out of the box |
| **pnpm** | `link:` dependencies + hoisting configuration | ✅ Working | Requires special config due to symlink behavior |
| **yarn** (Classic 1.x) | Standard `workspaces` field in package.json | ✅ Working | Works out of the box, simplest setup |
| **yarn** (Berry 4.x) | `nodeLinker: node-modules` in .yarnrc.yml | ⚠️ Partial | Installs + creates symlinks but command syntax incompatible |

### Phase 1.8: Source Code Installation Requirements (COMPLETED)

**Goal**: ✅ Investigate if source code can be removed from installation sandbox to simplify implementation

**Status**: ✅ **COMPLETED** - Confirmed that source code must be included in the installation sandbox

**Key Finding**: TypeScript requires source files to be present in the execution sandbox, even with proper `node_modules` symlinks.

**Investigation Results**:
- ❌ **Without source code**: TypeScript fails with `error TS18003: No inputs were found in config file`
- ✅ **With source code**: TypeScript compilation proceeds normally (may still have dependency resolution issues)

**Root Cause**: TypeScript reads the `include` paths from `tsconfig.json` (e.g., `["src/**/*"]`) and expects to find actual source files at those locations. The `node_modules` symlinks handle dependency resolution but cannot replace the need for source files.

**Implementation Impact**: 
- The current approach of including all workspace source files in the input digest is **correct and necessary**
- Cannot simplify by relying only on `node_modules` symlinks for TypeScript execution
- Source file inclusion is fundamental to TypeScript's compilation model

**Technical Details**:
- Config-only sandbox: Contains `tsconfig.json`, `package.json`, and `node_modules` but no `.ts`/`.tsx` files
- TypeScript error: Cannot find any inputs matching the `include` patterns in configuration
- Execution sandbox structure confirmed via `--keep-sandboxes=always` inspection

### Phase 1.9: JavaScript Backend Modifications Cleanup (COMPLETED)

**Goal**: ✅ Remove temporary `include_typescript_sources` modifications from JavaScript backend

**Status**: ✅ **COMPLETED** - Successfully removed all temporary debugging modifications

**Key Finding**: The temporary modifications added to the JavaScript backend during pnpm debugging are **no longer needed** and have been safely removed.

**Modifications Removed**:
1. **`InstalledNodePackageRequest.include_typescript_sources`** parameter (nodejs_tool.py:190, install_node_package.py:49)
2. **TypeScript source inclusion logic** in `_get_relevant_source_files()` (install_node_package.py:82-85)
3. **Debug logging** from installation and tool execution (install_node_package.py:112-164, nodejs_tool.py:185-191)
4. **Unused imports and parameters** cleanup (install_node_package.py:34, 41, 92-94)

**Why These Can Be Removed**:
- TypeScript check rule provides source files directly via `all_workspace_sources` glob
- JavaScript backend only needs to provide `node_modules` with package dependencies and symlinks
- Clear separation of concerns: JS backend handles installation, TS backend handles source inclusion
- Both parts work together without coupling through the installation system

**Architecture Validation**:
- ✅ TypeScript check continues to work with same functionality
- ✅ Package manager compatibility (npm, pnpm, Yarn Classic) maintained
- ✅ Workspace symlink resolution still works
- ✅ Clean separation between installation and source file management

**Result**: The JavaScript backend is now restored to its clean state while the TypeScript check implementation handles all TypeScript-specific requirements independently.

## Test Coverage Analysis and Gaps

### Current Test Coverage Status

**JavaScript Backend (`nodejs_tool_test.py`)**:
- ✅ Package manager command generation (npm, yarn, pnpm)
- ✅ Version configuration and overrides
- ✅ Resolve-based tool execution basic functionality
- ✅ Binary name override (e.g., typescript package → tsc binary)

**TypeScript Backend**:
- ✅ TSConfig parsing and extends resolution (`tsconfig_test.py`)
- ❌ **Missing**: TypeScript check rule integration tests
- ❌ **Missing**: Workspace package resolution tests
- ❌ **Missing**: Package manager compatibility tests

### Critical Test Gaps Identified

1. **Input Digest Pass-Through Not Tested**:
   - All existing `nodejs_tool_test.py` tests use `EMPTY_DIGEST`
   - No verification that `request.input_digest` is properly included in `Process.input_digest`
   - **Root Cause**: This gap allowed the missing `input_digest` merge bug to go undetected

2. **Resolve-Based Execution With Custom Input**:
   - Missing tests for `_run_tool_with_resolve()` with non-empty input digests
   - No verification of the critical merge: `merge_digests([request.input_digest, installed.digest])`
   - No tests ensuring both source files AND installed packages are present in execution

3. **TypeScript Check Integration**:
   - No end-to-end tests for `pants check` on TypeScript code
   - No tests for workspace package resolution (e.g., `@pants-example/common-types` imports)
   - No tests verifying package manager compatibility (npm, pnpm, yarn) with TypeScript check

4. **Package Manager Workspace Scenarios**:
   - Missing tests for pnpm `link:` protocol workspace dependencies
   - Missing tests for Yarn Classic workspace resolution
   - Missing tests for npm workspace compatibility

### Recommended Test Additions (Future Work)

**Phase A: Core Infrastructure Tests**
```python
# nodejs_tool_test.py additions
def test_tool_request_preserves_input_digest()
def test_resolve_based_execution_merges_input_and_installation()
def test_input_digest_with_custom_files()
```

**Phase B: TypeScript Check Integration Tests**  
```python
# check_test.py (new file)
def test_typescript_check_basic_compilation()
def test_typescript_check_with_workspace_packages()
def test_typescript_check_npm_package_manager()
def test_typescript_check_pnpm_package_manager()
def test_typescript_check_yarn_package_manager()
def test_typescript_check_workspace_symlink_resolution()
```

**Phase C: Error Handling and Edge Cases**
```python
def test_typescript_check_missing_dependencies()
def test_typescript_check_invalid_workspace_config()
def test_typescript_check_cross_package_type_errors()
```

### Why These Tests Matter

- **Prevent Regressions**: The `input_digest` merge bug would have been caught with proper test coverage
- **Validate Package Manager Compatibility**: Ensure npm, pnpm, and Yarn Classic continue working
- **Document Expected Behavior**: Tests serve as executable documentation for workspace resolution
- **Enable Confident Refactoring**: Comprehensive tests allow safe architectural improvements

### Test Implementation Priority

1. **High Priority**: `input_digest` pass-through tests (prevent critical bugs)
2. **Medium Priority**: TypeScript check integration tests (validate core functionality)  
3. **Low Priority**: Edge case and error handling tests (polish and robustness)

### Yarn 4 (Berry) Investigation Results

**Status**: ⚠️ **PARTIALLY WORKING** - Package installation and workspace symlinks work, but Pants command syntax is incompatible

**Configuration Used**:
```yaml
# .yarnrc.yml
nodeLinker: node-modules
enableGlobalCache: false
```

**What Works**:
- ✅ Package installation with `yarn@4.5.3`
- ✅ Workspace symlink creation at root level
- ✅ `node_modules/@pants-example/*` symlinks created correctly
- ✅ Compatible with Pants digest merging

**What Doesn't Work**:
- ❌ Pants command execution fails with "Unknown Syntax Error"
- ❌ Yarn 4 doesn't recognize `yarn --silent exec -- tsc` command syntax
- ❌ Expected: `yarn exec tsc` (Yarn 4 syntax) vs Actual: `yarn --silent exec -- tsc` (Yarn 1.x syntax)

**Root Cause**: Pants package manager configuration for Yarn uses `execute_args=("--silent", "exec", "--")` which is Yarn 1.x syntax. Yarn 4 requires updated command structure.

**Required Pants Changes for Full Yarn 4 Support**:
1. Update `PackageManager.yarn()` to detect Yarn 4.x versions
2. Use `execute_args=("exec",)` for Yarn 4.x instead of `("--silent", "exec", "--")`
3. Handle Yarn 4 command differences in package manager abstraction

**Workaround**: Use Yarn 1.22.22 (Classic) which is fully supported and provides identical functionality.


### Phase 2: Dynamic Project Resolution and Generic TypeScript Check

**Goal**: Remove hard-coded project paths and make TypeScript check work with any targets/projects

**Current Issue**: TypeScript check implementation hard-codes `src/python/pants/backend/typescript/examples/**/` paths, making it only work with the examples directory.

**Target Flow**:
1. **Target Analysis**: Given input targets (e.g., `pants check src/my-app::`), determine which TypeScript sources need checking
2. **Project Discovery**: Identify which NodeJS projects/resolves contain the target sources
3. **Workspace Resolution**: For each project, determine the complete workspace scope needed for type checking
4. **Execution**: Run TypeScript check on the complete workspace(s) with proper dependency resolution
5. **Result Aggregation**: Collect and report results from all checked projects

**Tasks**:
1. **Remove Hard-Coded Paths**
   - Replace hard-coded `examples/**/` glob patterns with dynamic target-based source discovery
   - Use target source files to determine workspace root and project boundaries
   - Implement project detection logic based on `package.json` and `tsconfig.json` locations

2. **Project-to-Resolve Mapping**
   - Given TypeScript target sources, determine which NodeJS resolve they belong to
   - Group targets by their containing project/resolve
   - Ensure each project is type-checked as a complete unit (with all workspace dependencies)

3. **Dynamic Workspace Discovery**
   - From target files, discover the workspace root (where root `package.json`/`tsconfig.json` exists)
   - Identify all workspace packages that need to be included for cross-package type resolution
   - Build complete source file list dynamically based on workspace configuration

4. **Configuration Path Resolution**
   - Dynamically locate `tsconfig.json`, `package.json`, and workspace config files
   - Support multiple project layouts (not just the examples structure)
   - Handle relative path resolution for project references and extends

**Implementation Strategy**:
- Leverage existing NodeJS project detection from JavaScript backend
- Use target source paths to infer project structure
- Build on existing `TSConfig` parsing but make it target-driven
- Maintain workspace-level type checking (don't regress to file-by-file checking)

**Acceptance Criteria**:
- ✅ `pants check path/to/any-typescript-project::` works (not just examples)
- ✅ Cross-package imports resolve correctly in any workspace structure  
- ✅ TypeScript configuration is discovered and applied dynamically
- ✅ Multiple targets from same project are batched into single type check execution
- ✅ No hard-coded paths remain in implementation

**Out of Scope for Phase 2**:
- Multiple resolve/project support (will be addressed later with updated examples)
- Performance optimization across projects
- Complex project reference scenarios

**Expected Architecture After Phase 2**:
```python
# Target sources → Project discovery → Workspace resolution → Type checking
targets = [typescript_target1, typescript_target2, ...]
projects = discover_typescript_projects(targets)
for project in projects:
    workspace_sources = discover_workspace_sources(project)
    workspace_config = discover_workspace_config(project) 
    typecheck_result = run_typescript_check(workspace_sources, workspace_config)
```

### Phase 3: Performance and Optimization

**Goal**: Ensure typechecking is fast and cache-friendly

**Tasks**:
1. **Multi-package incremental compilation**
   - Extend single-package incremental compilation to handle cross-package dependencies
   - Cache `.tsbuildinfo` files for multiple related packages
   - Optimize for repeated executions across package boundaries

2. **Dependency batching**
   - Batch related packages for efficient compilation
   - Determine optimal compilation units
   - Leverage Pants' dependency graph for batching decisions

3. **Parallel execution**
   - Ensure independent packages can be checked in parallel
   - Handle shared dependencies efficiently

**Acceptance Criteria**:
- Subsequent runs are significantly faster
- Independent packages can be checked in parallel
- Cache invalidation works correctly

### Phase 4: Polish and Production Features

**Goal**: Production-ready polish and advanced features

**Tasks**:
1. **Advanced error formatting and reporting**
   - Improve error message formatting and colors
   - Handle warnings vs errors appropriately
   - Add structured error output options

2. **Advanced tooling integration**
   - Support for TypeScript language server features
   - Integration with source maps for debugging
   - Support for custom TypeScript plugins

**Acceptance Criteria**:
- Error messages are clear, actionable, and well-formatted
- Advanced tooling scenarios work smoothly
- Production-ready stability and performance

## Technical Architecture

### File Structure
```
src/python/pants/backend/typescript/
├── subsystem.py              # TypeScript tool configuration
├── check.py                  # Core typechecking rules
├── check_test.py            # Unit tests
├── check_integration_test.py # Integration tests
└── examples/                # Test examples (existing)
```

### Key Components

1. **TypeScriptSubsystem**
   ```python
   class TypeScriptSubsystem(NodeJSToolBase):
       options_scope = "typescript"
       default_version = "typescript@5.8.2"
       _binary_name = "tsc"
   ```

2. **Check Request/Result**
   ```python
   @dataclass(frozen=True)
   class TypeScriptCheckRequest(CheckRequest):
       tool_subsystem = TypeScriptSubsystem

   @dataclass(frozen=True) 
   class TypeScriptCheckResult(CheckResult):
       # Standard CheckResult fields
   ```

3. **Main Check Rule**
   ```python
   @rule
   async def typecheck_typescript(
       request: TypeScriptCheckRequest,
       typescript: TypeScriptSubsystem,
   ) -> TypeScriptCheckResult:
       # Implementation
   ```

### Integration Points

1. **NodeJS Tool Pattern**: Follow existing patterns from prettier, eslint
2. **Check Goal Integration**: Use same patterns as terraform, java, go (modern experimental backends)
3. **Dependency Resolution**: Leverage existing JavaScript dependency inference
4. **Configuration**: Leverage existing `TSConfig` parsing from `pants.backend.typescript.tsconfig`

## Testing Strategy

### Unit Tests
- TypeScript tool subsystem configuration
- Error parsing and formatting
- Configuration file handling

### Integration Tests  
- End-to-end typechecking scenarios
- Multi-package workspace scenarios
- Error reporting accuracy
- Performance characteristics

### Manual Testing
- Use `examples/` directory for manual testing
- Test with real-world TypeScript projects
- Verify IDE integration

## Implementation Phases Timeline

- **Phase 1**: 2-3 weeks - Core tool integration
- **Phase 2**: 2-3 weeks - Workspace dependency handling  
- **Phase 3**: 1-2 weeks - Performance optimization
- **Phase 4**: 1-2 weeks - Polish and advanced features

**Total Estimated Time**: 6-10 weeks

## Future Enhancements (Backlog)

### High Priority
1. **TypeScript Project References Dependency Inference**
   - Parse `tsconfig.json` `references` fields
   - Map project references to Pants target dependencies
   - Enable better incremental compilation

2. **Declaration File Generation**
   - Support `tsc --declaration` for library packages
   - Package declaration files with distributions
   - Handle declaration maps for debugging

### Medium Priority
3. **Build/Compilation Support**
   - Add `pants package` support for TypeScript compilation
   - Generate JavaScript output with source maps
   - Handle different module formats (ESM, CommonJS)

4. **Advanced Dependency Resolution**
   - Support TypeScript path mapping (`paths` in tsconfig.json)
   - Handle conditional exports from package.json
   - Improve monorepo package resolution

### Low Priority
5. **Tool Integration**
   - Add tslint/eslint TypeScript rules support
   - Integrate with other TypeScript tools (ts-node, etc.)
   - Support custom TypeScript transformers

## Risks and Mitigation

### Risk: Performance Issues
- **Mitigation**: Implement incremental compilation early, benchmark regularly

### Risk: Complex Configuration Handling
- **Mitigation**: Start with simple cases, gradually add complexity

### Risk: Cross-Package Dependencies
- **Mitigation**: Leverage existing JavaScript dependency inference, test thoroughly

### Risk: Maintaining Compatibility
- **Mitigation**: Follow established patterns from JavaScript backend, extensive testing

## Success Metrics

1. **Functionality**: All TypeScript files in examples/ can be typechecked
2. **Performance**: Typechecking completes in reasonable time (<30s for examples)
3. **Accuracy**: Type errors are correctly identified and reported
4. **Integration**: Works seamlessly with existing Pants workflows
5. **Adoption**: Can be used on real TypeScript projects

## Dependencies

- **JavaScript Backend**: Core dependency for NodeJS tool patterns
- **Check Goal**: Existing check infrastructure
- **Examples**: Current examples/ directory for testing

## Documentation Requirements

1. Update TypeScript backend documentation
2. Add typechecking examples to README
3. Document configuration options
4. Add troubleshooting guide

---

This plan provides a structured approach to implementing TypeScript typechecking while maintaining compatibility with existing Pants patterns and the JavaScript ecosystem.
