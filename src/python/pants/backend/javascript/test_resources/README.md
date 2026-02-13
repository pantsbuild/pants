# JavaScript Backend Test Resources

This directory contains test project fixtures for the JavaScript backend tests.

## Structure

Each subdirectory represents a complete, working JavaScript project that can be used by tests:

- `basic_package/` - Simple single-package project with no dependencies
- `jest_project/` - Complete jest test project with source and test files
- `mocha_project/` - Complete mocha test project with source and test files

## Usage

Use `load_js_test_project()` from `pants.backend.javascript.testutil` to load test resources:

```python
from pants.backend.javascript.testutil import load_js_test_project

# Load all files for a specific package manager
test_files = load_js_test_project("jest_project", package_manager="npm")

# Override specific files when needed
test_files["jest_project/src/index.mjs"] = "export function add(x, y) { return x - y }"

rule_runner.write_files(test_files)
```

## Package Manager Support

Projects include lockfiles for all supported package managers (npm, pnpm, yarn).
Tests select the appropriate lockfile based on the `--nodejs-package-manager` option.

## Regenerating Lockfiles

To update lockfiles after modifying package.json:

```bash
cd jest_project

# npm
npm install --package-lock-only

# pnpm
pnpm install --lockfile-only

# yarn
yarn install --mode update-lockfile
```
