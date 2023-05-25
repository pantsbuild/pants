---
title: "2.1.x"
slug: "release-notes-2-1"
hidden: true
createdAt: "2020-10-30T23:13:20.237Z"
---
Some highlights:

- Speedup of dependency inference, around ~30% faster when used in the Pants codebase.
- New `export-codegen` goal.
- New `pants.backend.python.mixed_interpreter_constraints` backend with a `py-constraints` goal to debug what interpreter constraints are used by code, and `py-constraints --summary` to get an overview of your repo's interpreter constraints. See [Interpreter compatibility](doc:python-interpreter-compatibility) and our [blog post](https://blog.pantsbuild.org/python-3-migrations/) about this.
- New shorthand for the `entry_point` field. If you specify the `sources` field, you can set `entry_point=":my_func"`, and Pants will add the source's module name as the prefix. See [package](doc:python-package-goal).
- New `./pants help subsystems` command to list all configurable option scopes.
- Support for remote caching without remote execution. See [Remote Execution](doc:remote-execution).

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.1.x.rst) for a detailed change log.