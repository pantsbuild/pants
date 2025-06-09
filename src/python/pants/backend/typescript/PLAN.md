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

### Phase 2: Workspace and Cross-Package Dependencies

**Goal**: Handle monorepo scenarios with package dependencies

**Tasks**:
1. **Dependency resolution**
   - Extend existing import analysis to understand workspace package imports
   - Ensure `@pants-example/common-types` imports resolve to correct targets
   - Handle `node_modules` resolution for external packages

2. **Multi-package compilation context**
   - Determine when to include multiple packages in single `tsc` invocation
   - Handle TypeScript project references in compilation
   - Manage `node_modules` and workspace linking

3. **Configuration handling**
   - Read and merge `tsconfig.json` configurations
   - Handle `extends` and project references
   - Respect compiler options and path mappings

**Acceptance Criteria**:
- `pants check examples/main-app::` works with cross-package imports
- Workspace package dependencies are resolved
- TypeScript configuration is properly applied

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
