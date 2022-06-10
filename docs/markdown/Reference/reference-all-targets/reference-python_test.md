---
title: "python_test"
slug: "reference-python_test"
hidden: false
createdAt: "2022-06-02T21:10:49.247Z"
updatedAt: "2022-06-02T21:10:49.679Z"
---
A single Python test file, written in either Pytest style or unittest style.

All test util code, including `conftest.py`, should go into a dedicated `python_source` target and then be included in the `dependencies` field. (You can use the `python_test_utils` target to generate these `python_source` targets.)

See [test](doc:python-test-goal)

Backend: <span style="color: purple"><code>pants.backend.python</code></span>

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>extra_env_vars</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Additional environment variables to include in test processes. Entries are strings in the form `ENV_VAR=value` to use explicitly; or just `ENV_VAR` to copy the value of a variable in Pants's own environment. This will be merged with and override values from [test].extra_env_vars.

## <code>interpreter_constraints</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The Python interpreters this code is compatible with.

Each element should be written in pip-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`. You can leave off `CPython` as a shorthand, e.g. `>=2.7` will be expanded to `CPython>=2.7`.

Specify more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']` means either PyPy 3.7 _or_ CPython 3.7.

If the field is not set, it will default to the option `[python].interpreter_constraints`.

See [Interpreter compatibility](doc:python-interpreter-compatibility) for how these interpreter constraints are merged with the constraints of dependencies.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[python].resolves` to use.

If not defined, will default to `[python].default_resolve`.

All dependencies must share the same value for their `resolve` field.

## <code>runtime_package_dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to targets that can be built with the `./pants package` goal and whose resulting artifacts should be included in the test run.

Pants will build the artifacts as if you had run `./pants package`. It will include the results in your test's chroot, using the same name they would normally have, but without the `--distdir` prefix (e.g. `dist/`).

You can include anything that can be built by `./pants package`, e.g. a `pex_binary`, `python_awslambda`, or an `archive`.

## <code>skip_autoflake</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.python.lint.autoflake</code></span>

If true, don't run Autoflake on this target's code.

## <code>skip_bandit</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.bandit</code></span>

If true, don't run Bandit on this target's code.

## <code>skip_black</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.black</code></span>

If true, don't run Black on this target's code.

## <code>skip_docformatter</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.docformatter</code></span>

If true, don't run Docformatter on this target's code.

## <code>skip_flake8</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.flake8</code></span>

If true, don't run Flake8 on this target's code.

## <code>skip_isort</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.isort</code></span>

If true, don't run isort on this target's code.

## <code>skip_mypy</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.typecheck.mypy</code></span>

If true, don't run MyPy on this target's code.

## <code>skip_pylint</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.pylint</code></span>

If true, don't run Pylint on this target's code.

## <code>skip_pyupgrade</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.python.lint.pyupgrade</code></span>

If true, don't run pyupgrade on this target's code.

## <code>skip_tests</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, don't run this target's tests.

## <code>skip_yapf</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.python.lint.yapf</code></span>

If true, don't run yapf on this target's code.

## <code>source</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

A single file that belongs to this target.

Path is relative to the BUILD file's directory, e.g. `source='example.ext'`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>timeout</code>

<span style="color: purple">type: <code>int | None</code></span>
<span style="color: green">default: <code>None</code></span>

A timeout (in seconds) used by each test file belonging to this target.

If unset, will default to `[pytest].timeout_default`; if that option is also unset, then the test will never time out. Will never exceed `[pytest].timeout_maximum`. Only applies if the option `--pytest-timeouts` is set to true (the default).