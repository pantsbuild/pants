---
title: "1.29.x"
slug: "release-notes-1-29"
hidden: true
createdAt: "2020-05-20T00:54:47.325Z"
---
Some highlights:

- The `run`, `test`, and `setup-py` goals support passing arguments via `--`, e.g. `./pants test test_app.py -- -vv -k test_demo`.
- Python linters can now run on both Python 2 and Python 3 targets in the same run. See [lint](doc:python-lint-goal).
- Added support for Pylint source plugins. See [Linters and formatters](doc:python-linters-and-formatters).
- Added the `filter` goal. See [Project introspection](doc:project-introspection).
- Code generators will now automatically add the generator's runtime dependencies. See [Protobuf](doc:protobuf).
- Resolving requirements should be a bit faster thanks to better caching.
- Improved the Pants daemon (pantsd). It should now be safe to turn on with the option `enable_pantsd = true` in the `[GLOBAL]` scope. Pantsd substantially improves Pants performance and caching.
- Removed deprecated `source` field in BUILD files in favor of `sources`.
- Removed several deprecated V1 backends and plugins.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.29.x.rst) for a detailed change log.