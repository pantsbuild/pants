# Style Guide and Conventions

## Code Style

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

For subsystem/target help strings that render as documentation:
- Use `softwrap()` for multiline strings
- Use `help_text()` for `Field`/`Target` subclasses if needed for mypy
- Use backticks for config sections, CLI args, target names, inline code
- Use 2-space indentation for bullet/numbered lists (or `bullet_list()`)
- Never use indentation for code blocks; use triple-backtick blocks only
- Text in angle brackets (`<value>`) will be ignored unless wrapped in backticks

### Imports

- Imports are auto-sorted by `isort` (via ruff)
- Prefer absolute imports
- Group: stdlib, third-party, pants imports

### File headers

All source files must have this copyright header:

```python
# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
```

BUILD files use the same header (configured in `[tailor]` in `pants.toml`).

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

## Testing Conventions

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

### Integration tests

- Use `setup_tmpdir()` + `run_pants()` for full integration tests
- `run_pants()` is hermetic by default (doesn't read `pants.toml`)
- Pass `--backend-packages` explicitly in test args
- Use `result.assert_success()` / `result.assert_failure()`

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

### Cherry-picking

For backporting fixes to stable branches:
1. Label PR as `needs-cherrypick`
2. Set milestone to oldest release branch
3. Automation handles cherry-pick after merge

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
