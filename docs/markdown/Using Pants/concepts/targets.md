---
title: "Targets and BUILD files"
slug: "targets"
excerpt: "Metadata for your code."
hidden: false
createdAt: "2020-02-25T17:44:15.007Z"
---
Most goals require metadata about your code. For example, to run a test, you need to know about all the transitive dependencies of that test. You may also want to set a timeout on that test.

_Targets_ are an _addressable_ set of metadata describing your code.

For example:

- `shell_source` and `python_test` describe first-party code
- `python_requirement` describes third-party requirements
- `pex_binary` and `archive` describe artifacts you'd like Pants to build

To reduce boilerplate, some targets also generate other targets:

- `python_tests` -> `python_test`
- `shell_sources` -> `shell_source`
- `go_mod` -> `go_third_party_package`

BUILD files
===========

Targets are defined in files with the name `BUILD`. For example:

```python helloworld/greet/BUILD
python_tests(
    name="tests",
    timeout=120,
)

pex_binary(
    name="bin",
    entry_point="app.py:main",
)
```

Each target type has different _fields_, or individual metadata values. Run `pants help $target` to see which fields a particular target type has, e.g. `pants help file`. Most fields are optional and use sensible defaults. See [Field default values](doc:targets#field-default-values) for how you may override a field's default value.

All target types have a `name` field, which is used to identify the target. Target names must be unique within a directory.

You can autoformat `BUILD` files by enabling a `BUILD` file formatter by adding it to `[GLOBAL].backend_packages` in `pants.toml` (such as `pants.backend.build_files.fmt.black` [or others](doc:enabling-backends)). Then to format, run `pants fmt '**/BUILD'` or `pants fmt ::` (formats everything).


Environment variables
---------------------

BUILD files are very hermetic in nature with no support for using `import` or other I/O operations. In order to have dynamic data in BUILD files, you may inject values from the local environment using the `env()` function. It takes the variable name and optional default value as arguments.

```python helloworld/pkg/BUILD
python_distribution(
  name="helloworld-dist",
  description=env("DIST_DESC", "Set the `DIST_DESC` env variable to override this value."),
  provides=python_artifact(
    name="helloworld",
    version=env("HELLO_WORLD_VERSION"),
  ),
)
```

Target addresses
================

A target is identified by its unique address, in the form `path/to/dir:name`. The above example has the addresses `helloworld/greet:tests` and `helloworld/greet:bin`.

Addresses are used in the `dependencies` field to depend on other targets. Addresses can also be used as command-line arguments, such as `pants fmt path/to:tgt`.

(Both "generated targets" and "parametrized targets" have a variant of this syntax; see the below sections.)

> 📘 Default for the `name` field
>
> The `name` field defaults to the directory name. So, this target has the address `helloworld/greet:greet`.
>
> ```python
> # helloworld/greet/BUILD
> python_sources()
> ```
>
> You can refer to this target with either `helloworld/greet:greet` or the abbreviated form `helloworld/greet`.

> 📘 Use `//:tgt` for the root of your repository
>
> Addresses defined in the `BUILD` file at the root of your repository are prefixed with `//`, e.g. `//:my_tgt`.

`source` and `sources` field
============================

Targets like `python_test` and `resource` have a `source: str` field, while target generators like `python_tests` and `resources` have a `sources: list[str]` field. This determines which source files belong to the target.

Values are relative to the BUILD file's directory. Sources must be in or below this directory, i.e. `../` is not allowed.

The `sources` field also supports `_` and `**` as globs. To exclude a file or glob, prefix with `!`. For example, `["_.py", "!exclude_*.py"]` will include `f.py` but not `exclude_me.py`.

```python BUILD
resource(name="logo", source="logo.png")

python_tests(
    name="tests",
    sources=["*_test.py"],
)
```

> 🚧 Be careful with overlapping `source` fields
>
> It's legal to include the same file in the `source` / `sources` field for multiple targets.
>
> When would you do this? Sometimes you may have conflicting metadata for the same source file, such as wanting to check that a Shell test works with multiple shells. Normally, you should prefer Pants's `parametrize` mechanism to do this. See the below section "Parametrizing Targets".
>
> Often, however, it is not intentional when multiple targets own the same file. For example, this often happens when using `**` globs, like this:
>
> ```python
> # project/BUILD
> python_sources(sources=["**/*.py"])
>
> # project/subdir/BUILD
> python_sources(sources=["**/*.py"])
> ```
>
> Including the same file in the `source` / `sources` field for multiple targets can result in two confusing behaviors:
>
> - File arguments will run over all owning targets, e.g. `pants test path/to/test.ext` would run both test targets as two separate subprocesses, even though you might only expect a single subprocess.
> - Pants will sometimes no longer be able to infer dependencies on this file because it cannot disambiguate which of the targets you want to use. You must use explicit dependencies instead. (For some blessed fields, like the `resolve` field, if the targets have different values, then there will not be ambiguity.)
>
> You can run `pants list path/to/file.ext` to see all "owning" targets to check if >1 target has the file in its `source` field.

`dependencies` field
====================

A target's dependencies determines which other first-party code and third-party requirements to include when building the target.

Usually, you leave off the `dependencies` field thanks to _dependency inference_. Pants will read your import statements and map those imports back to your first-party code and your third-party requirements. You can run `pants dependencies path/to:target` to see what dependencies Pants infers.

However, dependency inference cannot infer everything, such as dependencies on `resource` and `file` targets.

To add an explicit dependency, add the target's address to the `dependencies` field. This augments any dependencies that were inferred.

```python helloworld/greet/BUILD
python_sources(
    name="lib",
    dependencies=[
        "3rdparty/python:ansicolors",
        "assets:logo,
    ],
)
```

You only need to declare direct dependencies. Pants will pull in _transitive dependencies_—i.e. the dependencies of your dependencies—for you.

> 📘 Relative addresses, `:tgt`
>
> When depending on a target defined in the same BUILD file, you can simply use `:tgt_name`, rather than `helloworld/greet:tgt_name`, for example.
>
> Addresses for generated targets also support relative addresses in the `dependencies` field, as explained in the "Target Generation" section below.

> 📘 Ignore dependencies with `!` and `!!`
>
> If you don't like that Pants inferred a certain dependency—as reported by [`pants dependencies path/to:tgt`](doc:project-introspection)—tell Pants to ignore it with `!`:
>
> ```python
> python_sources(
>     name="lib",
>     dependencies=["!3rdparty/python:numpy"],
> )
> ```
>
> You can use the prefix `!!` to transitively exclude a dependency, meaning that even if a target's dependencies include the bad dependency, the final result will not include the value.
>
> Transitive excludes can only be used in target types that conventionally are not depended upon by other targets, such as `pex_binary`, `python_distribution`, and `python_test` / `python_tests`. This is meant to limit confusion, as using `!!` in something like a `python_source` / `python_sources` target could result in surprising behavior for everything that depends on it. (Pants will print a helpful error when using `!!` when it's not legal.)

Field default values
====================

As mentioned above in [BUILD files](doc:targets#build-files), most target fields have sensible defaults. And it's easy to override those values on a specific target. But applying the same non-default value on many targets can get unwieldy, error-prone and hard to maintain. Enter `__defaults__`.

Alternative default field values are set using the `__defaults__` BUILD file symbol, and apply to targets in the filesystem tree under that BUILD file's directory.

The defaults are provided as a dictionary mapping target types to the default field values. Multiple target types may share the same set of default field values, when grouped together in parentheses (as a Python tuple).

Use the `all` keyword argument to provide default field values that should apply to all targets.

The `extend=True` keyword argument allows to add to any existing default field values set by a previous `__defaults__` call rather than replacing them.

Default fields and values are validated against their target types, except when provided using the `all` keyword, in which case only values for fields applicable to each target are validated. Use `ignore_unknown_fields=True` to ignore invalid fields.

This means, that it is legal to provide a default value for `all` targets, even if it is only a subset of targets that actually supports that particular field.

> 📘 `__defaults__` does not apply to environment targets.
>
> The environment targets (such as `local_environment` and `docker_environment` etc) are special and used during a bootstrap phase before any targets are defined and as such can not be targeted by the `__defaults__` construct.

Examples:

```python src/example/BUILD
    # Provide default `tags` to all targets in this subtree, and skip black, where applicable.
    __defaults__(all=dict(tags=["example"], skip_black=True))
```

Subdirectories may override defaults from a parent BUILD file:

```python src/example/override/BUILD
    # For `files` and `resources` targets, we want to use some other defaults.
    __defaults__({
      (files, resources): dict(tags=["example", "overridden"], description="Our assets")
    })
```

Use the `extend=True` keyword to update defaults rather than replace them, for any given target.

```python src/example/extend/BUILD
    # Add a default description to all types, in addition to the inherited default tags.
    __defaults__(extend=True, all=dict(description="Add default description to the defaults."))
```

To reset any modified defaults, simply override with the empty dict:

```python src/example/nodefaults/BUILD
    __defaults__(all={})
```

Supporting optional plugin fields
---------------------------------

Normally Pants presents an error message when attempting to provide a default value for a field that doesn't exist for the target. However, some fields comes from plugins, and to support disabling a plugin without having to remove any default values referencing any plugin fields it was providing, there is a `ignore_unknown_fields` option to use:

```python example/BUILD
    __defaults__(
      {
        # Defaults...
      },
      ignore_unknown_fields=True,
    )
```

Extending field defaults
------------------------

To add to a default value rather than replacing it, the current default value for a target field is available in the BUILD file using `<target>.<field>.default`. This allows you to augment a field's default value with much more precision. As an example, if you want to make the default sources for a `python_sources` target to work recursively you may specify a target augmenting the default sources field:

```python BUILD
python_sources(
  name="my-one-top-level-target",
  sources=[
    f"{pattern[0] if pattern.startswith("!") else ""}**/{pattern.lstrip("!")}"
    for pattern in python_sources.sources.default
  ]
)
```


Target generation
=================

To reduce boilerplate, Pants provides target types that generate other targets. For example:

- `files` -> `file`
- `python_tests` -> `python_test`
- `go_mod` -> `go_third_party_package`

Usually, prefer these target generators. [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) will automatically add them for you.

Run `pants help targets` to see how the target determines what to generate. Targets for first-party code, like `resources` and `python_tests`, will generate one target for each file in their `sources` field.

```python
python_sources(
    name="lib",
    # Will generate two `python_source` targets.
    sources=["app.py", "util.py"],
)
```

(Usually, you can leave off the `sources` field. When possible, it defaults to all relevant files in the current directory.)

Typically, fields declared in the target generator will be inherited by each generated target. For example, if you set `timeout=120` in a `python_tests` target, each generated `python_test` target will have `timeout=120`. You can instead use the `overrides` field for more granular metadata:

```python helloworld/BUILD
python_tests(
    name="tests",
    # This applies to every generated target.
    extra_env_vars=["MY_ENV_VAR"],
    # These only apply to the relevant generated targets.
    overrides={
        "dirutil_test.py": {"timeout": 30},
        ("osutil_test.py", "strutil_test.py"): {"timeout": 15},
    },
)
```

> 🚧 Field default values for generated targets
>
> [Default field values](doc:targets#field-default-values) apply to target generators, _not_ to generated targets. For example, if you have:
>
> ```python
> __defaults__({python_test: {"timeout": 30}})
>
> python_tests(sources=["test_*.py", "!test_special.py"])
> python_test(name="special", source="test_special.py")
> ```
>
> Then the default `timeout` value will only apply to the "special" `python_test`, not to any of the targets generated by the `python_tests` target.
>
> To specify defaults for both generated and manually-written instances of a target, you must list the target generator in your `__defaults__` as well:
>
> ```python
> __defaults__({(python_test, python_tests): {"timeout": 30}})
> ```

The address for generated targets depends if the generated target is for first-party code or not:

[block:parameters]
{
  "data": {
    "h-0": "Generated target type",
    "h-1": "Generated address syntax",
    "0-0": "First-party, e.g. `python_source` and `file`",
    "0-1": "`path/to/file.ext:tgt_generator`  \n  \nExample: `src/py/app.py:lib`  \n  \nThe address always starts with the path to the file.  \n  \nIf the file lives in the same directory as the target generator and the target generator left off the `name` field, you can use just the file path. For example, `src/py/app.py` (without the `:lib` suffix).  \n  \nIf the file lives in a subdirectory of the target generator, the suffix will look like `../tgt_generator`. For example, `src/py/subdir/f.py:../lib`, where the target generator is `src/py:lib`.  \n  \nWith the `dependencies` field, you can use relative addresses by prefixing the path with `./`, so long as the path is in the same directory or below the current BUILD file. For example, `./app.py:lib` rather than `src/py/app.py:lib`.",
    "1-0": "All other targets, e.g. `go_third_party_package`",
    "1-1": "`path/to:tgt_generator#generated_name`  \n  \nExample: `3rdparty/py:reqs#django`  \n  \nRun `pants help $target_type` on the target generator to see how it sets the generated name. For example, `go_mod` uses the Go package's name.  \n  \nIf the target generator left off the `name` field, you can leave it off for the generated address too, e.g. `3rdparty/py#django` (without the `:reqs` portion).  \n  \nWith the `dependencies` field, you can use relative addresses to reference generated targets in the same BUILD file, e.g. `:generator#generated_name` instead of `src/py:generated#generated_name`. If the target generator uses the default `name`, you can simply use `#generated_name`."
  },
  "cols": 2,
  "rows": 2,
  "align": [
    "left",
    "left"
  ]
}
[/block]

Run [`pants list dir:`](doc:project-introspection) in the directory of the target generator to see all generated target addresses, and [`pants peek dir:`](doc:project-introspection) to see all their metadata.

You can use the address for the target generator as an alias for all of its generated targets. For example, if you have the `files` target `assets:logos`, adding `dependencies=["assets:logos"]`to another target will add a dependency on each generated `file` target. Likewise, if you have a `python_tests` target `project:tests`, then `pants test project:tests` will run on each generated `python_test` target.

> 📘 Tip: one BUILD file per directory
>
> Target generation means that it is technically possible to put everything in a single BUILD file.
>
> However, we've found that it usually scales much better to use a single BUILD file per directory. Even if you start with using the defaults for everything, projects usually need to change some metadata over time, like adding a `timeout` to a test file or adding `dependencies` on resources.
>
> It's useful for metadata to be as fine-grained as feasible, such as by using the `overrides` field to only change the files you need to. Fine-grained metadata is key to having smaller cache keys (resulting in more cache hits), and allows you to more accurately reflect the status of your project. We have found that using one BUILD file per directory encourages fine-grained metadata by defining the metadata adjacent to where the code lives.
>
> [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) will automatically create targets that only apply metadata for the directory.

Parametrizing targets
=====================

It can be useful to create multiple targets describing the same entity, each with different metadata. For example:

- Run the same tests with different interpreter constraints, e.g. Python 2 vs Python 3.
- Declare that a file should work with multiple "resolves" (lockfiles).

The `parametrize` builtin creates a distinct target per parametrized field value. All values other than the parametrized field(s) are the same for each target. For example:

```python example/BUILD
# Creates two targets:
#
#    example:tests@shell=bash
#    example:tests@shell=zsh

shunit2_test(
    name="tests",
    source="tests.sh",
    shell=parametrize("bash", "zsh"),
)
```

If multiple fields are parametrized, a target will be created for each value in the Cartesian product, with `,` as the delimiter in the address. See the next example.

 If the field value is not a string—or it is a string but includes spaces—you can give it an alias, like the `interpreter_constraints` field below:

```python example/BUILD
# Creates four targets:
#
#    example:tests@interpreter_constraints=py2,resolve=lock-a
#    example:tests@interpreter_constraints=py2,resolve=lock-b
#    example:tests@interpreter_constraints=py3,resolve=lock-a
#    example:tests@interpreter_constraints=py3,resolve=lock-b

python_test(
    name="tests",
    source="tests.py",
    interpreter_constraints=parametrize(py2=["==2.7.*"], py3=[">=3.6,<3.7"]),
    resolve=parametrize("lock-a", "lock-b"),
)
```

To parametrize multiple fields together in groups, put each parametrization group as an unnamed (positional) argument to the target with the field values to use for that group as parametrization arguments. This is useful to avoid a full cartesian product if not every combination of field values makes sense. i.e. The previous example uses the same resolve (lockfile) for both interpreter constraints, however if you want to use a different resolve per interpreter, then grouping the resolve value with the interpreter constraint may be the way to go.

```python example/BUILD
# Creates two targets:
#
#    example:tests@parametrize=py2
#    example:tests@parametrize=py3

python_test(
    parametrize("py2", interpreter_constraints=["==2.7.*"], resolve="lock-a"),
    parametrize("py3", interpreter_constraints=[">=3.6,<3.7"], resolve="lock-b"),
    name="tests",
    source="tests.py",
)
```

The targets' addresses will have `@key=value` at the end, as shown above. Run [`pants list dir:`](doc:project-introspection) in the directory of the parametrized target to see all parametrized target addresses, and [`pants peek dir:`](doc:project-introspection) to see all their metadata.

Generally, you can use the address without the `@` suffix as an alias to all the parametrized targets. For example, `pants test example:tests` will run all the targets in parallel. Use the more precise address if you only want to use one parameter value, e.g. `pants test example:tests@shell=bash`.

Parametrization can be combined with target generation. The `@key=value` will be added to the end of the address for each generated target. For example:

```python example/BUILD
# Generates four `shunit2_test` targets:
#
#    example/test1.sh:tests@shell=bash
#    example/test1.sh:tests@shell=zsh
#    example/test2.sh:tests@shell=bash
#    example/test2.sh:tests@shell=zsh
#
# Also creates two `shunit2_tests` target
# generators, which can be used as aliases
# to their generated targets:
#
#    example:tests@shell=bash
#    example:tests@shell=zsh
#
# Generally, you can still use `example:tests`
# without the `@` suffix as an alias to all the
# created targets.

shunit2_tests(
    name="tests",
    sources=["test1.sh", "test2.sh"],
    shell=parametrize("bash", "zsh"),
)
```

You can combine `parametrize` with the `overrides` field to set more granular metadata for generated targets:

```python example/BUILD
# Generates three `shunit2_test` targets:
#
#    example/test1.sh:tests
#    example/test2.sh:tests@shell=bash
#    example/test2.sh:tests@shell=zsh
#
# The `shunit2_tests` target generator
# `example:tests` can be used as an alias
# to all 3 created targets.

shunit2_tests(
    name="tests",
    sources=["test1.sh", "test2.sh"],
    overrides={
        "test2.sh": {"shell": parametrize("bash", "zsh")},
    },
)
```
