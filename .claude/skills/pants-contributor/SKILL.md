---
name: pants-contributor
description: Expert guide for contributing to the Pants build system repo. Use when working on Pants source code, writing or running tests, creating or modifying backends/plugins, interacting with the build system, understanding the codebase architecture, or when the user needs help with any Pants development workflow. Triggers on questions about BUILD files, rules, targets, goals, running tests, linting, formatting, or any Pants build system interaction.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Agent
---

# Pants Build System Contributor Guide

You are an expert contributor to the [Pants](https://github.com/pantsbuild/pants) build system. This is the Pants repo itself -- a self-hosting build system where `./pants` runs Pants from source. You must follow the conventions, architecture, and workflows specific to this codebase.

For detailed reference on specific topics, see:
- [Build System Commands](./build-commands.md) - How to run tests, lint, format, typecheck
- [Architecture Guide](./architecture.md) - Codebase structure, rules API, backends
- [Style and Conventions](./style-conventions.md) - Code style, patterns, PR workflow

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

Every directory with source code needs a `BUILD` file. Common patterns in this repo:

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

## Quick Reference

### Common commands

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

### Target address syntax

- `path/to/dir:target_name` - specific target
- `path/to/dir:` - all targets in directory
- `path/to/dir::` - all targets recursively
- `path/to/file.py` - file address (inferred target)
- `::` - everything in the repo

### Key directories

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

### Python resolves (lockfiles)

The repo uses multiple Python resolves configured in `pants.toml`:
- `python-default` - Main resolve for Pants source code
- `pytest` - Test runner dependencies
- `mypy` - Type checker dependencies
- `flake8` - Linter dependencies

To regenerate lockfiles: `pants generate-lockfiles --resolve=<name>`

## Writing Rules (Plugin Code)

### Rule basics

Rules are async Python functions decorated with `@rule`:

```python
from pants.engine.rules import rule, collect_rules

@rule
async def my_rule(request: MyRequest) -> MyResult:
    # Pure function - no side effects!
    # Use engine APIs for processes, filesystem, etc.
    return MyResult(...)

def rules():
    return collect_rules()
```

### Key patterns

- **Frozen dataclasses** for all request/result types: `@dataclass(frozen=True)`
- **`await` engine intrinsics** for processes, filesystem ops, etc.
- **`concurrently()`** for parallel rule execution (never `await` in a loop)
- **`**implicitly()`** for implicit parameter injection
- **`collect_rules()`** to auto-discover rules in a module
- **Register in `register.py`** with `rules()` and `target_types()` functions

### Testing rules

Tests use `RuleRunner` for integration testing or `run_rule_with_mocks` for unit testing:

```python
from pants.testutil.rule_runner import RuleRunner, QueryRule

@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*my_module.rules(), QueryRule(Output, [Input])],
        target_types=[MyTarget],
    )

def test_my_rule(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({
        "src/BUILD": "my_target(name='t', source='f.py')",
        "src/f.py": "...",
    })
    result = rule_runner.request(Output, [Input(...)])
    assert result == expected
```

### Backend structure

Each backend lives in `src/python/pants/backend/<name>/` with:
- `register.py` - Entry point: exports `rules()`, `target_types()`, `build_file_aliases()`
- `target_types.py` - Target and field definitions
- `goals/` - Goal implementations (test, lint, fmt, etc.)
- `util_rules/` - Shared utility rules
- `subsystems/` - Tool subsystem definitions
- `dependency_inference/` - Dep inference rules

## Style Guide Essentials

- Use **f-strings** (not `.format()` or `%`)
- Prefer **conditional expressions** (ternary)
- Prefer **early returns**
- Use **collection literals** and **unpacking** for merging
- Prefer **comprehensions** over loops for creating collections
- Use **frozen dataclasses** (`@dataclass(frozen=True)`)
- **All functions must have type annotations** (parameters + return type)
- Use **`cast()`** over variable annotations for type overrides
- Use **Pytest-style** tests (not `unittest`)
- Comments: complete sentences, end with period, max 100 chars, space after `#`
- TODOs: link to GitHub issue `# TODO(#1234): Description.`
- Use `softwrap` helper for multiline help strings
