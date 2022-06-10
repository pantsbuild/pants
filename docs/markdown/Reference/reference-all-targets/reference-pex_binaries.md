---
title: "pex_binaries"
slug: "reference-pex_binaries"
hidden: false
createdAt: "2022-06-02T21:10:40.014Z"
updatedAt: "2022-06-02T21:10:40.569Z"
---
Generate a `pex_binary` target for each entry_point in the `entry_points` field.

This is solely meant to reduce duplication when you have multiple scripts in the same directory; it's valid to use a distinct `pex_binary` target for each script/binary instead.

This target generator does not work well to generate `pex_binary` targets where the entry point is for a third-party dependency. Dependency inference will not work for those, so you will have to set lots of custom metadata for each binary; prefer an explicit `pex_binary` target in that case. This target generator works best when the entry point is a first-party file, like `app.py` or `app.py:main`.

Backend: <span style="color: purple"><code>pants.backend.python</code></span>

## <code>complete_platforms</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The platforms the built PEX should be compatible with.

There must be built wheels available for all of the foreign platforms, rather than sdists.

You can give a list of multiple complete platforms to create a multiplatform PEX, meaning that the PEX will be executable in all of the supported environments.

Complete platforms should be addresses of `file` targets that point to files that contain complete platform JSON as described by Pex (https://pex.readthedocs.io/en/latest/buildingpex.html#complete-platform).

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

## <code>emit_warnings</code>

<span style="color: purple">type: <code>bool | None</code></span>
<span style="color: green">default: <code>None</code></span>

Whether or not to emit PEX warnings at runtime.

The default is determined by the option `emit_warnings` in the `[pex-binary-defaults]` scope.

## <code>entry_points</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The entry points for each binary, i.e. what gets run when when executing `./my_app.pex.`

Use a file name, relative to the BUILD file, like `app.py`. You can also set the function to run, like `app.py:func`. Pants will convert these file names into well-formed entry points, like `app.py:func` into `path.to.app:func.`

If you want the entry point to be for a third-party dependency or to use a console script, use the `pex_binary` target directly.

## <code>execution_mode</code>

<span style="color: purple">type: <code>'venv' | 'zipapp' | None</code></span>
<span style="color: green">default: <code>&#x27;zipapp&#x27;</code></span>

The mode the generated PEX file will run in.

The traditional PEX file runs in a modified 'zipapp' mode (See: https://www.python.org/dev/peps/pep-0441/) where zipped internal code and dependencies are first unpacked to disk. This mode achieves the fastest cold start times and may, for example be the best choice for cloud lambda functions.

The fastest execution mode in the steady state is 'venv', which generates a virtual environment from the PEX file on first run, but then achieves near native virtual environment start times. This mode also benefits from a traditional virtual environment `sys.path`, giving maximum compatibility with stdlib and third party APIs.

## <code>ignore_errors</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

Should PEX ignore when it cannot resolve dependencies?

## <code>include_requirements</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

Whether to include the third party requirements the binary depends on in the packaged PEX file.

## <code>include_tools</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

Whether to include Pex tools in the PEX bootstrap code.

With tools included, the generated PEX file can be executed with `PEX_TOOLS=1 <pex file> --help` to gain access to all the available tools.

## <code>inherit_path</code>

<span style="color: purple">type: <code>'fallback' | 'false' | 'prefer' | None</code></span>
<span style="color: green">default: <code>None</code></span>

Whether to inherit the `sys.path` (aka PYTHONPATH) of the environment that the binary runs in.

Use `false` to not inherit `sys.path`; use `fallback` to inherit `sys.path` after packaged dependencies; and use `prefer` to inherit `sys.path` before packaged dependencies.

## <code>interpreter_constraints</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The Python interpreters this code is compatible with.

Each element should be written in pip-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`. You can leave off `CPython` as a shorthand, e.g. `>=2.7` will be expanded to `CPython>=2.7`.

Specify more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']` means either PyPy 3.7 _or_ CPython 3.7.

If the field is not set, it will default to the option `[python].interpreter_constraints`.

See [Interpreter compatibility](doc:python-interpreter-compatibility) for how these interpreter constraints are merged with the constraints of dependencies.

## <code>layout</code>

<span style="color: purple">type: <code>'loose' | 'packed' | 'zipapp' | None</code></span>
<span style="color: green">default: <code>&#x27;zipapp&#x27;</code></span>

The layout used for the PEX binary.

By default, a PEX is created as a single file zipapp, but either a packed or loose directory tree based layout can be chosen instead.

A packed layout PEX is an executable directory structure designed to have cache-friendly characteristics for syncing incremental updates to PEXed applications over a network. At the top level of the packed directory tree there is an executable `__main__.py` script. The directory can also be executed by passing its path to a Python executable; e.g: `python packed-pex-dir/`. The Pex bootstrap code and all dependency code are packed into individual zip files for efficient caching and syncing.

A loose layout PEX is similar to a packed PEX, except that neither the Pex bootstrap code nor the dependency code are packed into zip files, but are instead present as collections of loose files in the directory tree providing different caching and syncing tradeoffs.

Both zipapp and packed layouts install themselves in the `$PEX_ROOT` as loose apps by default before executing, but these layouts compose with `execution_mode='zipapp'` as well.

## <code>overrides</code>

<span style="color: purple">type: <code>Dict[Union[str, Tuple[str, ...]], Dict[str, Any]] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Override the field values for generated `pex_binary` targets.

Expects a dictionary mapping values from the `entry_points` field to a dictionary for their overrides. You may either use a single string or a tuple of strings to override multiple targets.

For example:

    ```
    overrides={
      "foo.py": {"execution_mode": "venv"]},
      "bar.py:main": {"restartable": True]},
      ("foo.py", "bar.py:main"): {"tags": ["legacy"]},
    }
    ```

Every key is validated to belong to this target's `entry_points` field.

If you'd like to override a field's value for every `pex_binary` target generated by this target, change the field directly on this target rather than using the `overrides` field.

You can specify the same entry_point in multiple keys, so long as you don't override the same field more than one time for the entry_point.

## <code>platforms</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The abbreviated platforms the built PEX should be compatible with.

There must be built wheels available for all of the foreign platforms, rather than sdists.

You can give a list of multiple platforms to create a multiplatform PEX, meaning that the PEX will be executable in all of the supported environments.

Platforms should be in the format defined by Pex (https://pex.readthedocs.io/en/latest/buildingpex.html#platform), i.e. PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-37-cp37m", "macosx_10.12_x86_64-cp-310-cp310"):

  - PLATFORM: the host platform, e.g. "linux-x86_64", "macosx-10.12-x86_64".
  - IMPL: the Python implementation abbreviation, e.g. "cp" or "pp".
  - PYVER: a two or more digit string representing the python major/minor version (e.g., "37" or "310") or else a component dotted version string (e.g., "3.7" or "3.10.1").
  - ABI: the ABI tag, e.g. "cp37m", "cp310", "abi3", "none".

Note that using an abbreviated platform means that certain resolves will fail when they encounter environment markers that cannot be deduced from the abbreviated platform string. A common example of this is 'python_full_version' which requires knowing the patch level version of the foreign Python interpreter. To remedy this you should use a 3-component dotted version for PYVER. If your resolves fail due to more esoteric undefined environment markers, you should switch to specifying `complete_platforms` instead.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[python].resolves` to use.

If not defined, will default to `[python].default_resolve`.

All dependencies must share the same value for their `resolve` field.

## <code>resolve_local_platforms</code>

<span style="color: purple">type: <code>bool | None</code></span>
<span style="color: green">default: <code>None</code></span>

For each of the `platforms` specified, attempt to find a local interpreter that matches.

If a matching interpreter is found, use the interpreter to resolve distributions and build any that are only available in source distribution form. If no matching interpreter is found (or if this option is `False`), resolve for the platform by accepting only pre-built binary distributions (wheels).

## <code>restartable</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, runs of this target with the `run` goal may be interrupted and restarted when its input files change.

## <code>shebang</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Set the generated PEX to use this shebang, rather than the default of PEX choosing a shebang based on the interpreter constraints.

This influences the behavior of running `./result.pex`. You can ignore the shebang by instead running `/path/to/python_interpreter ./result.pex`.

## <code>strip_pex_env</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

Whether or not to strip the PEX runtime environment of `PEX*` environment variables.

Most applications have no need for the `PEX*` environment variables that are used to control PEX startup; so these variables are scrubbed from the environment by Pex before transferring control to the application by default. This prevents any subprocesses that happen to execute other PEX files from inheriting these control knob values since most would be undesired; e.g.: PEX_MODULE or PEX_PATH.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.