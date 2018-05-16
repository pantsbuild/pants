# mypy static type analyzer

This Pants plugin runs the [mypy](http://mypy-lang.org/) static type checker for Python
against Python-related Pants targets. This provides access to `mypy`'s "gradual" static
typing checks.

## Prerequisites

A Python 3.x interpreter must be available to Pants' standard search method for Python
interpreters. (This is because, while `mypy` can check Python 2.7 code, `mypy` itself only runs
with Python 3.x.) The Pants plugin will use the available Python 3.x interpreter to install
its own copy of `mypy`.

## Usage

Just invoke the `mypy` task against any Python target(s). For example, if you had `python_library`
target identified by `src/python/foo/bar:baz`, run this command:

```
./pants mypy src/python/foo/bar:baz
```

The `mypy` task will pass through any extra command-line arguments directly to `mypy`. For example,
if you want to pass `--follow-imports=silent` to `mypy` for the same python_library target, run
this command:

```
./pants mypy src/python/foo/bar:baz -- --follow-imports=silent
```

See `mypy`'s usage screen for more information.

## Open Issues

- It remains to be seen how this plugin should deal with imports of third-party modules for which
there are no type stubs in the `typeshed` project. (A copy of `typeshed` is emedded For now, it is
recommended to pass `--follow-imports=silent` as a pass-through argument on the Pants
command-line.

## Links

- [PEP 484 - Type Hints](https://www.python.org/dev/peps/pep-0484/)
- [mypy](http://mypy-lang.org/) - [GitHub](https://github.com/python/mypy/)
- [typeshed](https://github.com/python/typeshed/)
