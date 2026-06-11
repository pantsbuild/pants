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

For any further usage assistance with Pants, consult the documentation under `docs/docs`.
