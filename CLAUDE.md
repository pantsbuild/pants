# Pants Build System Contributor Guide

This is the Pants build system repo -- a self-hosting build system where `./pants` runs Pants from source. Follow the conventions, architecture, and workflows specific to this codebase.

## Critical Rules

### ALWAYS use Pants, NEVER use raw Python tools

This is the most important rule. **Never** run `pytest`, `mypy`, `black`, `isort`, `flake8`, `ruff`, or any other Python tool directly. All Python tools must be invoked through Pants:

```bash
# CORRECT - always use Pants
pants test src/python/pants/backend/python/goals/pytest_runner_test.py
pants lint src/python/pants/backend/python/goals/pytest_runner.py
pants fmt src/python/pants/backend/python/goals/pytest_runner.py
pants check src/python/pants/backend/python/goals/pytest_runner.py

# WRONG - never do this
pytest src/python/pants/backend/python/goals/pytest_runner_test.py
mypy src/python/pants/backend/python/goals/pytest_runner.py
black src/python/pants/backend/python/goals/pytest_runner.py
ruff check src/python/pants/backend/python/goals/pytest_runner.py
```

### Running Pants from source

In this repo, `./pants` is a special bootstrap script that runs Pants from the local source tree. Use `pants` (which resolves to the `./pants` script) for all operations. The first run compiles the Rust engine and may take several minutes.

### Test file naming

Test files must be named `*_test.py` (not `test_*.py`). Pants discovers tests by this suffix.

### BUILD file conventions

Every directory with source code needs a `BUILD` file. Common patterns:

```python
# Standard source + test pattern
python_sources()
python_tests(name="tests")

# With test utilities (conftest, fixtures, helpers)
python_test_utils(name="test_utils")

# With overrides for specific files
python_sources(
    overrides={
        "special.py": {"dependencies": ["//some/dep"]},
    },
)
```

All BUILD files must have the copyright header:
```python
# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
```

## Common Commands

| Task | Command |
|------|---------|
| Run specific test file | `pants test path/to/file_test.py` |
| Run tests for changed files | `pants --changed-since=HEAD test` |
| Run tests with transitive deps | `pants --changed-since=HEAD --changed-dependents=transitive test` |
| Run a single test function | `pants test path/to/file_test.py -- -k test_function_name` |
| Debug a test (interactive) | `pants test --debug path/to/file_test.py` |
| Debug with specific test | `pants test --debug path/to/file_test.py -- -k test_name` |
| Lint changed files | `pants --changed-since=HEAD lint` |
| Format changed files | `pants --changed-since=HEAD fmt` |
| Type-check changed files | `pants --changed-since=HEAD check` |
| List all targets in dir | `pants list path/to/dir:` |
| Show dependencies | `pants dependencies path/to/target` |
| Show dependents | `pants dependents path/to/target` |
| Show target info | `pants peek path/to/target` |
| Generate BUILD files | `pants tailor` |
| Validate BUILD files | `pants lint --only=ruff-format '**BUILD'` |
| Run pre-push checks | `build-support/githooks/pre-push` |

### Test options

```bash
# Run tests matching a pattern
pants test path/to/file_test.py -- -k "test_foo or test_bar"

# Run with verbose output
pants test path/to/file_test.py -- -vvs

# Run with no timeout (useful for debugging)
pants test --timeout-default=0 path/to/file_test.py

# Show test output even on success
pants test --output=all path/to/file_test.py

# Force re-run (skip cache)
pants --no-local-cache test path/to/file_test.py
```

### Target address syntax

- `path/to/dir:target_name` - specific target
- `path/to/dir:` - all targets in directory
- `path/to/dir::` - all targets recursively
- `path/to/file.py` - file address (inferred target)
- `::` - everything in the repo

## Key Directories

| Path | Purpose |
|------|---------|
| `src/python/pants/` | Core Pants Python source code |
| `src/python/pants/backend/` | Language-specific backends (python, go, java, docker, etc.) |
| `src/python/pants/core/` | Core goals (test, lint, fmt, check, package, run) |
| `src/python/pants/engine/` | The Pants engine (rules, targets, processes, fs) |
| `src/rust/engine/` | Rust engine implementation |
| `pants-plugins/` | In-repo plugins (internal_plugins, pants_explorer) |
| `3rdparty/python/` | Third-party Python dependency declarations and lockfiles |
| `build-support/` | Build scripts, CI helpers, git hooks |
| `testprojects/` | Test fixture projects used by integration tests |
| `docs/docs/` | Documentation source (Docusaurus MDX) |

## Python Resolves (Lockfiles)

The repo uses multiple Python resolves configured in `pants.toml`:
- `python-default` - Main resolve for Pants source code
- `pytest` - Test runner dependencies
- `mypy` - Type checker dependencies
- `flake8` - Linter dependencies

To regenerate lockfiles: `pants generate-lockfiles --resolve=<name>`

## Engine Architecture

### The Rule Graph

Pants's engine is built around a **rule graph** - a directed graph where:
- **Rules** (`@rule` decorated async functions) are internal nodes
- **Queries** are entry points (roots)
- **Params** are typed, hashable input values (leaves)

Key properties:
- Rules are **pure functions** mapping input types to output types
- The engine handles **memoization**, **concurrency**, and **caching**
- Type annotations are used at runtime for dependency injection
- The engine uses **exact type matching** (no subtyping)

### Rule Execution

```python
from pants.engine.rules import rule, collect_rules, concurrently, implicitly
from pants.engine.intrinsics import execute_process

@rule
async def my_rule(request: MyRequest) -> MyResult:
    # Await other rules (engine manages execution)
    intermediate = await some_other_rule(request.field, **implicitly())

    # Run external processes through the engine
    process_result = await execute_process(
        Process(argv=["/bin/echo", "hello"], description="Echo"),
        **implicitly()
    )

    # Parallel execution with concurrently()
    results = await concurrently(
        process_thing(item, **implicitly()) for item in items
    )

    return MyResult(data=process_result.stdout)
```

### Union Rules (Polymorphism)

Since the engine uses exact type matching, polymorphism is achieved through **unions**:

```python
from pants.engine.unions import UnionRule, union

@union
class LintRequest:
    pass

@dataclass(frozen=True)
class MyLinterRequest(LintRequest):
    ...

# Register the union member
def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, MyLinterRequest),
    ]
```

### Rule Decorators

| Decorator | Purpose |
|-----------|---------|
| `@rule` | Standard async rule (cached, pure) |
| `@goal_rule` | Top-level CLI goal entry point |
| `@uncacheable_rule` | Rule that should not be memoized |

### Key Engine Types

| Type | Module | Purpose |
|------|--------|---------|
| `Process` | `pants.engine.process` | Run an external process |
| `ProcessResult` | `pants.engine.process` | Process execution result |
| `Digest` | `pants.engine.fs` | Content-addressed file tree |
| `Snapshot` | `pants.engine.fs` | Digest with file/dir listing |
| `MergeDigests` | `pants.engine.fs` | Combine multiple digests |
| `CreateDigest` | `pants.engine.fs` | Create files from content |
| `Target` | `pants.engine.target` | A build target |
| `Field` | `pants.engine.target` | A target field |
| `FieldSet` | `pants.engine.target` | Subset of fields for a rule |
| `Address` | `pants.engine.addresses` | Target address |

## Backend Structure

Each backend in `src/python/pants/backend/<name>/` follows this pattern:

### register.py (entry point)

```python
from pants.backend.foo import target_types_rules
from pants.backend.foo.goals import test, lint
from pants.backend.foo.target_types import FooTarget, FooTestTarget

def rules():
    return [
        *target_types_rules.rules(),
        *test.rules(),
        *lint.rules(),
    ]

def target_types():
    return [FooTarget, FooTestTarget]
```

The backend is activated in `pants.toml` via `backend_packages`:

```toml
[GLOBAL]
backend_packages = ["pants.backend.foo"]
```

### Target types

```python
from pants.engine.target import (
    Target,
    SingleSourceField,
    MultipleSourcesField,
    Dependencies,
    StringField,
)

class FooSourceField(SingleSourceField):
    expected_file_extensions = (".foo",)

class FooTarget(Target):
    alias = "foo_source"
    core_fields = (FooSourceField, Dependencies)
    help = "A Foo source file."
```

### Goal rules

```python
from pants.core.goals.test import TestResult, TestRequest

@dataclass(frozen=True)
class FooTestFieldSet(TestRequest.FieldSet):
    required_fields = (FooTestSourceField,)
    source: FooTestSourceField

class FooTestRequest(TestRequest):
    tool_subsystem = FooSubsystem
    field_set_type = FooTestFieldSet

@rule
async def run_foo_test(batch: FooTestRequest.Batch) -> TestResult:
    ...

def rules():
    return [
        *collect_rules(),
        *FooTestRequest.rules(),
    ]
```

## Configuration

### pants.toml

The main configuration file. Key sections:
- `[GLOBAL]` - Backend packages, pythonpath, sandboxing
- `[source]` - Source root patterns
- `[python]` - Python interpreter constraints, resolves, pip version
- `[pytest]` - Test runner args, resolve
- `[mypy]` - Type checker args, resolve
- `[test]` - Test timeout, env vars
- `[flake8]`, `[shellcheck]`, `[shfmt]` - Linter configs

### Python version

The repo currently targets **Python 3.14** (`interpreter_constraints = ["==3.14.*"]` in `pants.toml`).

## Style Guide

### Python style

- **f-strings**: Use f-strings, not `.format()` or `%`
- **Ternary expressions**: Prefer `x = "a" if cond else "b"` over if/else blocks
- **Early returns**: Prefer guard clauses, avoid deep nesting
- **Collection literals**: Use `{a}`, `(a, b)`, `{"k": v}` not constructors
- **Unpacking for merging**: `[*l1, *l2, "elem"]` not `l1 + l2 + ["elem"]`
- **Comprehensions**: Prefer over `map`/`filter` and explicit loops
- **Frozen dataclasses**: Always use `@dataclass(frozen=True)` for engine types
- **Type annotations**: Required on all functions (params + return type)
- **`cast()` over annotations**: Prefer `x = cast(str, untyped())` over `x: str = untyped()`
- **Pytest style**: Never use `unittest.TestCase`; use plain functions with `assert`
- **Error codes in type:ignore**: `# type: ignore[assignment]` not `# type: ignore`
- **Protocols for params**: Use `Iterable`, `Sequence`, `Mapping` not `List`, `Dict` in function params
- **Precise return types**: Return types should be concrete (`list[str]`, not `Iterable[str]`)

### Comments

- Must start with `# ` (space after hash)
- Must be complete sentences ending with a period
- Max 100 characters per line
- Explain **why**, not **what**
- TODOs must reference a GitHub issue: `# TODO(#1234): Description.`

### Help strings

- Use `softwrap()` for multiline strings
- Use `help_text()` for `Field`/`Target` subclasses if needed for mypy
- Use backticks for config sections, CLI args, target names, inline code
- Use 2-space indentation for bullet/numbered lists (or `bullet_list()`)
- Never use indentation for code blocks; use triple-backtick blocks only

### File headers

All source files must have the copyright header:

```python
# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
```

### Imports

- Imports are auto-sorted by `isort` (via ruff)
- Prefer absolute imports
- Group: stdlib, third-party, pants imports

## Engine-Specific Conventions

### Types for the rule graph

- Rule params and returns must be **hashable** and **immutable**
- Use `tuple` not `list`, `FrozenDict` not `dict`, `FrozenOrderedSet` not `set`
- Use `Collection[T]` to newtype a `tuple`
- Use `DeduplicatedCollection[T]` to newtype a `FrozenOrderedSet`
- The engine uses **exact type matching** (no subtype consideration)
- Newtype freely to disambiguate: `class Name(str): pass`

### Rule patterns

```python
# Standard rule with collect_rules
from pants.engine.rules import collect_rules, rule

@rule
async def my_rule(request: MyRequest) -> MyResult:
    ...

def rules():
    return collect_rules()
```

```python
# Using concurrently (NEVER await in a loop)
results = await concurrently(
    process_item(item, **implicitly()) for item in items
)
```

```python
# Running a process
from pants.engine.intrinsics import execute_process
from pants.engine.process import Process

result = await execute_process(
    Process(
        argv=["tool", "--flag", "arg"],
        input_digest=my_digest,
        description="Running tool",
    ),
    **implicitly()
)
```

### Registering rules

Each module has a `rules()` function, aggregated in `register.py`:

```python
# In each module
def rules():
    return collect_rules()

# In register.py
def rules():
    return [
        *module1.rules(),
        *module2.rules(),
    ]

def target_types():
    return [Target1, Target2]
```

## Testing

### Test function naming

- Test files: `*_test.py` (NOT `test_*.py`)
- Test functions: `def test_descriptive_name() -> None:`
- All test functions must have `-> None` return annotation

### Integration vs unit tests

- Unit tests: `*_test.py` - run in normal test target
- Integration tests: `*_integration_test.py` - get their own BUILD target with longer timeouts

```python
# In BUILD files, integration tests are separated:
python_tests(
    name="tests",
    sources=["*_test.py", "!*_integration_test.py"],
)
python_tests(
    name="integration",
    sources=["*_integration_test.py"],
    timeout=240,
)
```

### Skipping tests

The repo conftest.py enforces `--noskip` - skipped tests are treated as errors. If a test legitimately needs to be skippable (e.g., platform-specific), mark it:

```python
@pytest.mark.no_error_if_skipped
def test_platform_specific() -> None:
    ...
```

### RuleRunner fixtures

```python
@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*my_rules(), QueryRule(Output, [Input])],
        target_types=[MyTarget],
    )
```

- Each test gets a fresh `RuleRunner` instance (via fixture)
- Use `rule_runner.write_files()` to set up test content
- Use `rule_runner.set_options()` to configure options
- Use `rule_runner.request()` to invoke rules
- Use `rule_runner.run_goal_rule()` for goal rules

### Testing approaches

**Unit tests** - Test pure Python functions without the engine:
```python
def test_my_helper() -> None:
    assert my_function("input") == "expected"
```

**run_rule_with_mocks** - Test rule logic with mocked dependencies:
```python
from pants.testutil.rule_runner import run_rule_with_mocks

def test_my_rule() -> None:
    result = run_rule_with_mocks(
        my_rule,
        rule_args=[MyRequest(...)],
        mock_calls={
            "my.module.some_dependency": lambda req: MockResult(...),
        },
    )
    assert result == expected
```

**RuleRunner** - Test rules with a real engine and isolated filesystem:
```python
def test_integration(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({
        "src/BUILD": "my_target(source='f.py')",
        "src/f.py": "content",
    })
    rule_runner.set_options(["--my-option=value"])
    result = rule_runner.request(MyOutput, [MyInput(...)])
    assert result.field == expected
```

**run_pants()** - Full integration tests:
```python
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

def test_end_to_end() -> None:
    sources = {
        "src/BUILD": "python_sources()",
        "src/app.py": "print('hello')",
    }
    with setup_tmpdir(sources) as tmpdir:
        result = run_pants([
            "--backend-packages=['pants.backend.python']",
            "lint",
            f"{tmpdir}/src:",
        ])
    result.assert_success()
```

## PR and Contribution Workflow

### Before submitting

1. Format: `pants --changed-since=HEAD fmt`
2. Lint: `pants --changed-since=HEAD lint`
3. Type-check: `pants --changed-since=HEAD check`
4. Test: `pants --changed-since=HEAD --changed-dependents=transitive test`
5. Or run the pre-push hook: `build-support/githooks/pre-push`

### Commit messages

- Start with a verb (Add, Fix, Update, Remove, Refactor)
- Be concise but descriptive
- Reference GitHub issues where applicable

## Maintenance Tasks

### Updating external tool versions

For `ExternalTool` subclasses (downloaded binaries):
1. Download new version for each platform
2. Compute sha256 and byte length: `tee >(shasum -a 256) >(wc -c) > /dev/null < archive`
3. Update `default_version` and `default_known_versions`

### Updating Python tool versions

For `PythonToolBase` subclasses (PyPI packages):
1. Update `default_requirements` and/or `default_interpreter_constraints`
2. Run `build-support/bin/generate_builtin_lockfiles.py <scope>`

### Updating PEX

PEX is special - update both:
1. The `pex-cli` subsystem in `src/python/pants/backend/python/util_rules/pex_cli.py`
2. The requirement in `3rdparty/python/requirements.txt` and regenerate lockfile
