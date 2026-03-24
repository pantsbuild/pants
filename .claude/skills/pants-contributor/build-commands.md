# Pants Build Commands Reference

## Running Tests

### Basic test commands

```bash
# Test a specific file
pants test src/python/pants/backend/python/goals/pytest_runner_test.py

# Test all targets in a directory
pants test src/python/pants/backend/python/goals:

# Test recursively
pants test src/python/pants/backend/python/goals::

# Test changed files only
pants --changed-since=HEAD test

# Test changed files and their transitive dependents
pants --changed-since=HEAD --changed-dependents=transitive test

# Alias for the above
pants --all-changed test
```

### Test options

```bash
# Run a specific test function
pants test path/to/file_test.py -- -k test_function_name

# Run tests matching a pattern
pants test path/to/file_test.py -- -k "test_foo or test_bar"

# Run in debug mode (interactive, for debuggers)
pants test --debug path/to/file_test.py

# Run with verbose output
pants test path/to/file_test.py -- -vvs

# Run with no timeout (useful for debugging)
pants test --timeout-default=0 path/to/file_test.py

# Show test output even on success
pants test --output=all path/to/file_test.py

# Force re-run (skip cache)
pants --no-local-cache test path/to/file_test.py
```

### Test configuration

Tests are configured in `pants.toml`:
- Default args: `--no-header --noskip -vv`
- Default timeout: 60 seconds
- Pytest is installed from the `pytest` resolve
- Test execution slot variable: `TEST_EXECUTION_SLOT`

## Linting

```bash
# Lint specific files
pants lint src/python/pants/backend/python/goals/pytest_runner.py

# Lint changed files
pants --changed-since=HEAD lint

# Lint with a specific linter only
pants lint --only=flake8 path/to/file.py
pants lint --only=ruff-check path/to/file.py
pants lint --only=ruff-format path/to/file.py

# Lint BUILD files
pants lint --only=ruff-format '**BUILD'
```

Active linters (configured in `pants.toml`):
- `flake8` - Python linter (config at `build-support/flake8/.flake8`)
- `ruff check` - Fast Python linter
- `ruff format` - Python and BUILD file formatter
- `shellcheck` - Shell script linter
- `shfmt` - Shell script formatter
- `hadolint` - Dockerfile linter

## Formatting

```bash
# Format specific files
pants fmt src/python/pants/backend/python/goals/pytest_runner.py

# Format changed files
pants --changed-since=HEAD fmt

# Format everything (use sparingly)
pants fmt ::
```

## Type Checking

```bash
# Type-check specific files
pants check src/python/pants/backend/python/goals/pytest_runner.py

# Type-check changed files
pants --changed-since=HEAD check

# Type-check with transitive dependents
pants --changed-since=HEAD --changed-dependents=transitive check
```

MyPy is configured in `pants.toml` and installed from the `mypy` resolve.

## Dependency Management

```bash
# Show dependencies of a target
pants dependencies src/python/pants/backend/python:

# Show reverse dependencies (what depends on this)
pants dependents src/python/pants/backend/python:

# Generate/update lockfiles
pants generate-lockfiles --resolve=python-default
pants generate-lockfiles --resolve=pytest
pants generate-lockfiles --resolve=mypy

# Generate all lockfiles
pants generate-lockfiles
```

Third-party Python dependencies are declared in `3rdparty/python/` using `python_requirements()` targets referencing `requirements.txt` files.

## Introspection

```bash
# List targets in a directory
pants list src/python/pants/backend/python:

# Show detailed target info (as JSON)
pants peek src/python/pants/backend/python/goals:tests

# Show file dependencies
pants filedeps src/python/pants/backend/python/goals:

# Show the paths between two targets
pants paths --from=src/python/pants/engine --to=src/python/pants/core

# Count lines of code
pants count-loc ::
```

## BUILD File Management

```bash
# Auto-generate BUILD files for new source files
pants tailor

# Check for BUILD file issues
pants lint '**BUILD'

# Update BUILD file formatting
pants fmt '**BUILD'

# Update BUILD files for deprecations
pants update-build-files ::
```

## Running Scripts

```bash
# Run a Python script through Pants
pants run src/python/pants/backend/python/providers/python_build_standalone/scripts/generate_urls.py

# Run build support scripts
pants run build-support/bin/generate_builtin_lockfiles.py -- <scope>
```

## Pre-push Checks

Before pushing, run the pre-push hook to catch common issues:

```bash
build-support/githooks/pre-push
```

Or run format + lint on changed files:

```bash
pants --changed-since=HEAD fmt
pants --changed-since=HEAD lint
pants --changed-since=HEAD check
```

## Performance Tips

- Use `--changed-since=HEAD` to only operate on changed files
- Use `pantsd` (enabled by default) for faster startup
- For benchmarking: `hyperfine --warmup=1 --runs=5 'pants <command>'`
- Cold cache benchmark: `hyperfine --runs=5 'pants --no-pantsd --no-local-cache <command>'`
- To clear caches: restart pantsd with `pants --no-pantsd <command>` or kill it
