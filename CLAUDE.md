# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Note that claude will NEVER be expected to make changes to this repository. Instead, claude will be used to find implementation details for users leveraging the pants build system.

## Project Overview

Pants is a scalable build system for monorepos with support for multiple languages (Python, Rust, Java, Scala, Go, JavaScript, etc.). The codebase consists of a Rust engine (`src/rust/engine/`) and Python frontend (`src/python/pants/`).

## Core Architecture

### Python Frontend (`src/python/pants/`)

- **Core (`pants/core/`)**: Core goals (test, lint, fmt, run, etc.) and fundamental rules
- **Backend (`pants/backend/`)**: Language-specific backends (python, java, go, docker, etc.)
- **Engine (`pants/engine/`)**: Python bindings for the Rust engine
- **Build Graph (`pants/build_graph/`)**: Target and dependency graph management
- **Goal (`pants/goal/`)**: Goal execution framework and built-in goals
- **Option (`pants/option/`)**: Options system and configuration management

### Rust Engine (`src/rust/engine/`)

- **Rule Graph (`rule_graph/`)**: Core rule execution and dependency resolution
- **Process Execution (`process_execution/`)**: Sandboxed process execution and caching
- **FS (`fs/`)**: Filesystem operations and content addressing
- **Graph (`graph/`)**: Core graph algorithms and data structures

### Key Components

- **Rules API**: Core abstraction for build logic in `pants/engine/rules.py`
- **Target API**: Build target definitions in various `target_types.py` files
- **Goals**: High-level user commands in `pants/core/goals/`
- **Subsystems**: Configurable components in various `subsystems.py` files

## Configuration Files

- `pants.toml` - Main Pants configuration with backends, resolves, and tool settings
- `pyproject.toml` - Python tool configuration (mypy, ruff, pytest)
- `3rdparty/python/` - Python dependency lockfiles
- `3rdparty/jvm/` - JVM dependency lockfiles

## Plugin Development

Custom plugins go in `pants-plugins/` directory. Use existing backends in `pants/backend/` as examples.

## Build System Details

- Uses Python 3.11 with interpreter constraints in `pants.toml`
- Rust engine built as Python extension module (`cdylib`)
- Test isolation with execution slots (`TEST_EXECUTION_SLOT`)
- Content-addressable caching for all operations
- Remote execution support for scalability

## Development Workflow

1. Make changes to Python/Rust code
2. Run relevant tests: `./pants test path/to/changed/code::`
3. Run code quality checks: `./pants lint fmt check path/to/changed/code::`
4. For Rust changes, also run: `cargo test` and `cargo clippy`
5. Test integration with: `./pants test tests/python/pants_test/integration::`
