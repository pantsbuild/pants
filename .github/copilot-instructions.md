# Copilot Instructions for pantsbuild/pants

## Build & Test Commands

Pants is self-hosting — it uses itself (via `./pants`) to build, test, and lint.

```bash
# Run all Python tests
./pants test ::

# Run tests for a specific file
./pants test src/python/pants/backend/python/goals/pytest_runner_test.py

# Run tests for a specific directory
./pants test src/python/pants/backend/python/goals/

# Run a single test method (pass pytest args after --)
./pants test src/python/pants/backend/python/goals/pytest_runner_test.py -- -k test_name

# Lint and format (runs all configured tools: ruff, flake8, shellcheck, shfmt, hadolint, etc.)
./pants lint ::
./pants fmt ::

# Type-check with mypy
./pants check ::

# Run against changed files only
./pants --all-changed test

# Auto-generate BUILD files after adding/removing source files
./pants tailor ::

# Build/test the Rust native engine
./cargo test --locked --all --tests
./cargo test -p fs                    # single crate
./cargo test -p fs read_file_missing  # single test
./cargo clippy --locked --all
./cargo check                         # fast compile check
./cargo fmt
```

The `./cargo` wrapper script sets up the correct Python and environment variables before delegating to cargo inside `src/rust/`.

## Architecture

### Dual-language codebase

- **Python** (`src/python/pants/`): Rules, backends, goals, target types, and the plugin API.
- **Rust** (`src/rust/`): The core execution engine, filesystem, process execution, caching, and the native scheduler. Compiled into `native_engine.so` which Python calls via PyO3.
- The `./pants` bootstrap script compiles the Rust engine and places the `.so` into the Python source tree before running.

### Rule Engine

The engine is a demand-driven computation graph. Work is defined by **rules** — Python async functions decorated with `@rule`:

```python
@rule
async def compile_thing(request: CompileRequest, subsystem: MySubsystem) -> CompileResult:
    result = await some_other_rule(SomeInput(...), **implicitly())
    return CompileResult(result.output)
```

Key concepts:
- **Rules** (`@rule`): Async functions whose parameter types are automatically resolved by the engine. The return type annotation is the "product" the rule provides.
- **Goal rules** (`@goal_rule`): Entry points invoked by CLI commands (e.g., `test`, `lint`, `fmt`). Must return a `Goal` subclass.
- **`await` / `concurrently`**: Inside a rule, you request other computations by calling other rules or using `concurrently()` for parallel execution. There is no `Get()` anymore — use direct `await` on rule calls.
- **`**implicitly()`**: Pass this when calling a rule to allow the engine to supply implicit parameters.
- **Unions** (`@union`): Enable polymorphic dispatch — different backends can register implementations for the same abstract request type via `UnionRule`.

### Backend Structure

Each language/tool backend lives under `src/python/pants/backend/<name>/` (stable) or `src/python/pants/backend/experimental/<name>/` (experimental) and follows this structure:

- `register.py` — Entry point exposing `rules()`, `target_types()`, and optionally `build_file_aliases()`. Each function aggregates rules/types from submodules.
- `target_types.py` — Defines `Target` subclasses and their `Field` classes.
- `goals/` — Implementations of goals (test, lint, fmt, package, etc.) for that backend.
- `subsystems/` — Tool configuration (`Subsystem` subclasses with options).
- `util_rules/` — Shared helper rules.

Backends are enabled in `pants.toml` under `[GLOBAL].backend_packages`.

### Targets and Fields

Targets are declared in `BUILD` files and modeled as frozen collections of typed fields:

```python
class MyField(StringField):
    alias = "my_field"
    help = "Description."

class MyTarget(Target):
    alias = "my_target"
    core_fields = (*COMMON_TARGET_FIELDS, MyField, ...)
    help = "Description."
```

### Plugin System

Internal plugins live in `pants-plugins/` (added to `pythonpath` in `pants.toml`). Both internal and external plugins follow the same `register.py` pattern with `rules()` and `target_types()` functions.

Use `collect_rules()` at the bottom of a module to gather all `@rule`-decorated functions in that module for export.

## Key Conventions

- **`from __future__ import annotations`** — Used in most Python files; follow the convention of nearby files.
- **`__init__.py` files must be empty** — Enforced by CI. Notable exceptions: `pants/__init__.py` (namespace package path setup) and `pants/testutil/__init__.py` (pytest assertion rewriting). Do not add exports or side effects to `__init__.py` unless matching an existing exception.
- **Copyright headers** — Required on all `.py` (except `__init__.py`), `.rs`, and `.js` files:
  ```
  # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
  # Licensed under the Apache License, Version 2.0 (see LICENSE).
  ```
- **Test files** — Named `*_test.py` (unit) or `*_integration_test.py` (integration). Tests use `RuleRunner` to set up a sandboxed rule graph:
  ```python
  rule_runner = RuleRunner(rules=[*my_module.rules(), QueryRule(Output, [Input])])
  ```
- **Frozen collections** — Use `FrozenDict` and `FrozenOrderedSet` (from `pants.util`) instead of mutable dicts/sets in rule inputs/outputs, since all rule data must be hashable/immutable.
- **`@dataclass(frozen=True)`** — Used for all request/response types passed between rules.
- **Line length** — 100 characters (configured in ruff and enforced by linting).
- **Python version** — 3.14 (set in `pants.toml` under `[python].interpreter_constraints`).
- **Skipping tests** — `pytest.skip()` is treated as a test failure (via `--noskip`). Use the `@pytest.mark.no_error_if_skipped` marker if a skip is intentional.
