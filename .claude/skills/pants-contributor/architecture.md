# Pants Codebase Architecture

## Overview

Pants is a build system with a Python frontend and a Rust engine backend. The codebase is self-hosting: the `./pants` script in the repo root runs Pants from the local sources, compiling the Rust engine as needed.

## Source Code Layout

```
src/
  python/
    pants/                    # Core Pants package
      backend/                # Language-specific backends
        python/               # Python support (goals, rules, target types)
        go/                   # Go support
        java/                 # Java support
        scala/                # Scala support
        docker/               # Docker support
        shell/                # Shell support
        javascript/           # JavaScript/TypeScript support
        helm/                 # Helm chart support
        k8s/                  # Kubernetes support
        cc/                   # C/C++ support
        rust/                 # Rust support
        experimental/         # Experimental backends
        build_files/          # BUILD file formatting/fixing
        codegen/              # Code generation (protobuf, thrift, etc.)
        project_info/         # Introspection goals (filedeps, peek, etc.)
        plugin_development/   # Plugin dev support
      core/                   # Core goals and subsystems
        goals/                # test, lint, fmt, check, package, run, etc.
        target_types.py       # Core target types (files, resources, etc.)
        util_rules/           # Core utility rules
      engine/                 # The Python side of the engine
        rules.py              # @rule, collect_rules, concurrently, implicitly
        target.py             # Target, Field base classes
        process.py            # Process execution types
        fs.py                 # Filesystem types (Digest, Snapshot, etc.)
        intrinsics.py         # Engine intrinsic functions
        unions.py             # Union/polymorphism system
        internals/            # Internal engine implementation
      bin/                    # Entry points (pants_loader, native_client)
      option/                 # Options/configuration system
      build_graph/            # Build graph construction
      goal/                   # Goal infrastructure
      help/                   # Help system
      pantsd/                 # Pants daemon
      util/                   # Utility modules
      testutil/               # Test utilities (RuleRunner, etc.)
        rule_runner.py        # RuleRunner for integration tests
        pants_integration_test.py  # Full integration test harness
  rust/
    engine/                   # Rust engine implementation
      Cargo.toml              # Rust workspace root
      rule_graph/             # Rule graph construction
      process_execution/      # Process sandboxing and execution
      fs/                     # Filesystem implementation
      watch/                  # File watching
      ...

pants-plugins/                # In-repo plugins
  internal_plugins/           # Plugins used by the Pants repo itself
    releases/                 # Release management plugin
    test_lockfile_fixtures/   # Test lockfile fixture plugin
  pants_explorer/             # Pants Explorer web UI backend

3rdparty/
  python/                     # Python dependency declarations
    requirements.txt          # Main requirements
    user_reqs.lock            # Main lockfile (python-default resolve)
    pytest.lock               # Pytest resolve lockfile
    mypy.lock                 # MyPy resolve lockfile
    flake8.lock               # Flake8 resolve lockfile

build-support/
  bin/                        # Build support scripts
    generate_builtin_lockfiles.py  # Regenerate tool lockfiles
    generate_completions.py   # Generate shell completions
  flake8/                     # Flake8 configuration and plugins
  githooks/                   # Git hooks (pre-push)
  migration-support/          # Migration helpers
  preambles/                  # License header templates

testprojects/                 # Test fixture projects
  src/python/                 # Python test projects
  src/go/                     # Go test projects
  src/java/                   # Java test projects
  src/shell/                  # Shell test projects

docs/
  docs/                       # Documentation (Docusaurus)
    introduction/             # What is Pants, key concepts
    getting-started/          # Installation, first steps
    using-pants/              # User guide
    writing-plugins/          # Plugin development guide
    python/                   # Python-specific docs
    contributions/            # Contributor guide
      development/            # Dev setup, style guide, architecture
      releases/               # Release process
```

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

### pants.ci.toml

CI-specific overrides that layer on top of `pants.toml`.

### Python version

The repo currently targets **Python 3.14** (`interpreter_constraints = ["==3.14.*"]` in `pants.toml`).

## Testing Approaches

### 1. Unit tests (plain Python)

Test pure Python functions without the engine:

```python
def test_my_helper() -> None:
    assert my_function("input") == "expected"
```

### 2. run_rule_with_mocks (rule unit tests)

Test rule logic with mocked dependencies:

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

### 3. RuleRunner (rule integration tests)

Test rules with a real engine and isolated filesystem:

```python
from pants.testutil.rule_runner import RuleRunner, QueryRule

@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *my_module.rules(),
            QueryRule(MyOutput, [MyInput]),
        ],
        target_types=[MyTarget],
    )

def test_integration(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({
        "src/BUILD": "my_target(source='f.py')",
        "src/f.py": "content",
    })
    rule_runner.set_options(["--my-option=value"])
    result = rule_runner.request(MyOutput, [MyInput(...)])
    assert result.field == expected
```

### 4. run_pants() (full integration tests)

Test with a real Pants process:

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
