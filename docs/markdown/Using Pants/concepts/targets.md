---
title: "Targets and BUILD files"
slug: "targets"
excerpt: "Metadata for your code."
hidden: false
createdAt: "2020-02-25T17:44:15.007Z"
updatedAt: "2022-04-29T23:51:48.029Z"
---
Most goals require metadata about your code. For example, to run a test, you need to know about all the transitive dependencies of that test. You may also want to set a timeout on that test.

_Targets_ are an _addressable_ set of metadata describing your code.

For example:

* `shell_source` and `python_test` describe first-party code
* `python_requirement` describes third-party requirements
* `pex_binary` and `archive` describe artifacts you'd like Pants to build

To reduce boilerplate, some targets also generate other targets:

* `python_tests` -> `python_test`
* `shell_sources` -> `shell_source`
* `go_mod` -> `go_third_party_package`

# BUILD files

Targets are defined in files with the name `BUILD`. For example:
[block:code]
{
  "codes": [
    {
      "code": "python_tests(\n    name=\"tests\",\n    timeout=120,\n)\n\npex_binary(\n    name=\"bin\",\n    entry_point=\"app.py:main\",\n)",
      "language": "python",
      "name": "helloworld/greet/BUILD"
    }
  ]
}
[/block]
Each target type has different _fields_, or individual metadata values. Run `./pants help $target` to see which fields a particular target type has, e.g. `./pants help file`. Most fields are optional and use sensible defaults.

All target types have a `name` field, which is used to identify the target. Target names must be unique within a directory.

Use [`./pants tailor ::`](doc:create-initial-build-files) to automate generating BUILD files, and [`./pants update-build-files ::`](doc:reference-update-build-files) to reformat them (using `black`, [by default](doc:reference-update-build-files#section-formatter)).

# Target addresses

A target is identified by its unique address, in the form `path/to/dir:name`. The above example has the addresses `helloworld/greet:tests` and `helloworld/greet:bin`.

Addresses are used in the `dependencies` field to depend on other targets. Addresses can also be used as command-line arguments, such as `./pants fmt path/to:tgt`.

(Both "generated targets" and "parametrized targets" have a variant of this syntax; see the below sections.)
[block:callout]
{
  "type": "info",
  "title": "Default for the `name` field",
  "body": "The `name` field defaults to the directory name. So, this target has the address `helloworld/greet:greet`.\n\n```python\n# helloworld/greet/BUILD\npython_sources()\n```\n\nYou can refer to this target with either `helloworld/greet:greet` or the abbreviated form `helloworld/greet`."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Use `//:tgt` for the root of your repository",
  "body": "Addressed defined in the `BUILD` file at the root of your repository are prefixed with `//`, e.g. `//:my_tgt`."
}
[/block]
# `source` and `sources` field

Targets like `python_test` and `resource` have a `source: str` field, while target generators like `python_tests` and `resources` have a `sources: list[str]` field. This determines which source files belong to the target.

Values are relative to the BUILD file's directory. Sources must be in or below this directory, i.e. `../` is not allowed.

The `sources` field also supports `*` and `**` as globs. To exclude a file or glob, prefix with `!`. For example, `["*.py", "!exclude_*.py"]` will include `f.py` but not `exclude_me.py`.
[block:code]
{
  "codes": [
    {
      "code": "resource(name=\"logo\", source=\"logo.png\")\n\npython_tests(\n    name=\"tests\",\n    sources=[\"*_test.py\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "Be careful with overlapping `source` fields",
  "body": "It's legal to include the same file in the `source` / `sources` field for multiple targets. \n\nWhen would you do this? Sometimes you may have conflicting metadata for the same source file, such as wanting to check that a Shell test works with multiple shells. Normally, you should prefer Pants's `parametrize` mechanism to do this. See the below section \"Parametrizing Targets\".\n\nOften, however, it is not intentional when multiple targets on the same file. For example, this often happens when using `**` globs, like this:\n\n```python\n# project/BUILD\npython_sources(sources=[\"**/*.py\"])\n\n# project/subdir/BUILD\npython_sources(sources=[\"**/*.py\"])\n```\n\nIncluding the same file in the `source` / `sources` field for multiple targets can result in two confusing behaviors: \n\n* File arguments will run over all owning targets, e.g. `./pants test path/to/test.ext` would run both test targets as two separate subprocesses, even though you might only expect a single subprocess.\n* Pants will sometimes no longer be able to infer dependencies on this file because it cannot disambiguate which of the targets you want to use. You must use explicit dependencies instead. (For some blessed fields, like the `resolve` field, if the targets have different values, then there will not be ambiguity.)\n\nYou can run `./pants list path/to/file.ext` to see all \"owning\" targets to check if >1 target has the file in its `source` field."
}
[/block]
# `dependencies` field

A target's dependencies determines which other first-party code and third-party requirements to include when building the target.

Usually, you leave off the `dependencies` field thanks to _dependency inference_. Pants will read your import statements and map those imports back to your first-party code and your third-party requirements. You can run `./pants dependencies path/to:target` to see what dependencies Pants infers.

However, dependency inference cannot infer everything, such as dependencies on `resource` and `file` targets. 

To add an explicit dependency, add the target's address to the `dependencies` field. This augments any dependencies that were inferred.
[block:code]
{
  "codes": [
    {
      "code": "python_sources(\n    name=\"lib\",\n    dependencies=[\n        \"3rdparty/python:ansicolors\",\n        \"assets:logo,\n    ],\n)",
      "language": "python",
      "name": "helloworld/greet/BUILD"
    }
  ]
}
[/block]
You only need to declare direct dependencies. Pants will pull in _transitive dependencies_—i.e. the dependencies of your dependencies—for you.
[block:callout]
{
  "type": "info",
  "title": "Relative addresses, `:tgt`",
  "body": "When depending on a target defined in the same BUILD file, you can simply use `:tgt_name`, rather than `helloworld/greet:tgt_name`, for example. \n\nAddresses for generated targets also support relative addresses in the `dependencies` field, as explained in the \"Target Generation\" section below."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Ignore dependencies with `!` and `!!`",
  "body": "If you don't like that Pants inferred a certain dependency—as reported by [`./pants dependencies path/to:tgt`](doc:project-introspection)—tell Pants to ignore it with `!`:\n\n```python\npython_sources(\n    name=\"lib\",\n    dependencies=[\"!3rdparty/python:numpy\"],\n)\n```\n\nYou can use the prefix `!!` to transitively exclude a dependency, meaning that even if a target's dependencies include the bad dependency, the final result will not include the value. \n\nTransitive excludes can only be used in target types that conventionally are not dependend upon by other targets, such as `pex_binary` and `python_test` / `python_tests`. This is meant to limit confusion, as using `!!` in something like a `python_source` / `python_sources` target could result in surprising behavior for everything that depends on it. (Pants will print a helpful error when using `!!` when it's not legal.)"
}
[/block]
# Target generation

To reduce boilerplate, Pants provides target types that generate other targets. For example:

* `files` -> `file`
* `python_tests` -> `python_test`
* `go_mod` -> `go_third_party_package`

Usually, prefer these target generators. [`./pants tailor ::`](doc:create-initial-build-files) will automatically add them for you.

Run `./pants help targets` to see how the target determines what to generate. Targets for first-party code, like `resources` and `python_tests`, will generate one target for each file in their `sources` field.

```python
python_sources(
    name="lib",
    # Will generate two `python_source` targets.
    sources=["app.py", "util.py"],
)
```

(Usually, you can leave off the `sources` field. When possible, it defaults to all relevant files in the current directory.)

Typically, fields declared in the target generator will be inherited by each generated target. For example, if you set `timeout=120` in a `python_tests` target, each generated `python_test` target will have `timeout=120`. You can instead use the `overrides` field for more granular metadata:
[block:code]
{
  "codes": [
    {
      "code": "python_tests(\n    name=\"tests\",\n    # This applies to every generated target.\n    extra_env_vars=[\"MY_ENV_VAR\"],\n    # These only apply to the relevant generated targets.\n    overrides={\n        \"dirutil_test.py\": {\"timeout\": 30},\n        (\"osutil_test.py\", \"strutil_test.py\"): {\"timeout\": 15},\n    },\n)",
      "language": "python",
      "name": "helloworld/BUILD"
    }
  ]
}
[/block]
The address for generated targets depends if the generated target is for first-party code or not:
[block:parameters]
{
  "data": {
    "h-1": "Generated address syntax",
    "h-0": "Generated target type",
    "h-2": "",
    "0-0": "First-party, e.g. `python_source` and `file`",
    "1-0": "All other targets, e.g. `go_third_party_package`",
    "1-1": "`path/to:tgt_generator#generated_name`\n\nExample: `3rdparty/py:reqs#django`\n\nRun `./pants help $target_type` on the target generator to see how it sets the generated name. For example, `go_mod` uses the Go package's name.\n\nIf the target generator left off the `name` field, you can leave it off for the generated address too, e.g. `3rdparty/py#django` (without the `:reqs` portion).\n\nWith the `dependencies` field, you can use relative addresses to reference generated targets in the same BUILD file, e.g. `:generator#generated_name` instead of `src/py:generated#generated_name`. If the target generator uses the default `name`, you can simply use `#generated_name`.",
    "1-2": "`src/go:mod#github.com/google/uuid`",
    "0-2": "`src/py/app.py:lib`\n`src/py/util_test.py:tests`",
    "0-1": "`path/to/file.ext:tgt_generator`\n\nExample: `src/py/app.py:lib`\n\nThe address always starts with the path to the file.\n\nIf the file lives in the same directory as the target generator and the target generator left off the `name` field, you can use just the file path. For example, `src/py/app.py` (without the `:lib` suffix).\n\nIf the file lives in a subdirectory of the target generator, the suffix will look like `../tgt_generator`. For example, `src/py/subdir/f.py:../lib`, where the target generator is `src/py:lib`.\n\nWith the `dependencies` field, you can use relative addresses by prefixing the path with `./`, so long as the path is in the same directory or below the current BUILD file. For example, `./app.py:lib` rather than `src/py/app.py:lib`."
  },
  "cols": 2,
  "rows": 2
}
[/block]
Run [`./pants list dir:`](doc:project-introspection) in the directory of the target generator to see all generated target addresses, and [`./pants peek dir:`](doc:project-introspection) to see all their metadata.

You can use the address for the target generator as an alias for all of its generated targets. For example, if you have the `files` target `assets:logos`, adding `dependencies=["assets:logos"]`to another target will add a dependency on each generated `file` target. Likewise, if you have a `python_tests` target `project:tests`, then `./pants test project:tests` will run on each generated `python_test` target.
[block:callout]
{
  "type": "info",
  "title": "Tip: one BUILD file per directory",
  "body": "Target generation means that it is technically possible to put everything in a single BUILD file.\n\nHowever, we've found that it usually scales much better to use a single BUILD file per directory. Even if you start with using the defaults for everything, projects usually need to change some metadata over time, like adding a `timeout` to a test file or adding `dependencies` on resources. \n\nIt's useful for metadata to be as fine-grained as feasible, such as by using the `overrides` field to only change the files you need to. Fine-grained metadata is key to having smaller cache keys (resulting in more cache hits), and allows you to more accurately reflect the status of your project. We have found that using one BUILD file per directory encourages fine-grained metadata by defining the metadata adjacent to where the code lives.\n\n[`./pants tailor ::`](doc:create-initial-build-files) will automatically create targets that only apply metadata for the directory."
}
[/block]
# Parametrizing targets

It can be useful to create multiple targets describing the same entity, each with different metadata. For example:

- Run the same tests with different interpreter constraints, e.g. Python 2 vs Python 3.
- Declare that a file should work with multiple "resolves" (lockfiles).

The `parametrize` builtin creates a distinct target per parametrized field value. All values other than the parametrized field(s) are the same for each target. For example:
[block:code]
{
  "codes": [
    {
      "code": "# Creates two targets:\n#\n#    example:tests@shell=bash\n#    example:tests@shell=zsh\n\nshunit2_test(\n    name=\"tests\",\n    source=\"tests.sh\",\n    shell=parametrize(\"bash\", \"zsh\"),\n)",
      "language": "python",
      "name": "example/BUILD"
    }
  ]
}
[/block]
If multiple fields are parametrized, a target will be created for each value in the Cartesian product, with `,` as the delimiter in the address. See the next example.

 If the field value is not a string—or it is a string but includes spaces—you can give it an alias, like the `interpreter_constraints` field below:
[block:code]
{
  "codes": [
    {
      "code": "# Creates four targets:\n#\n#    example:tests@interpreter_constraints=py2,resolve=lock-a\n#    example:tests@interpreter_constraints=py2,resolve=lock-b\n#    example:tests@interpreter_constraints=py3,resolve=lock-a\n#    example:tests@interpreter_constraints=py3,resolve=lock-b\n\npython_test(\n    name=\"tests\",\n    source=\"tests.py\",\n    interpreter_constraints=parametrize(py2=[\"==2.7.*\"], py3=[\">=3.6\"]),\n    resolve=parametrize(\"lock-a\", \"lock-b\"),\n)",
      "language": "python",
      "name": "example/BUILD"
    }
  ]
}
[/block]
The targets' addresses will have `@key=value` at the end, as shown above. Run [`./pants list dir:`](doc:project-introspection) in the directory of the parametrized target to see all parametrized target addresses, and [`./pants peek dir:`](doc:project-introspection) to see all their metadata.

Generally, you can use the address without the `@` suffix as an alias to all the parametrized targets. For example, `./pants test example:tests` will run all the targets in parallel. Use the more precise address if you only want to use one parameter value, e.g. `./pants test example:tests@shell=bash`.

Parametrization can be combined with target generation. The `@key=value` will be added to the end of the address for each generated target. For example:
[block:code]
{
  "codes": [
    {
      "code": "# Generates four `shunit2_test` targets:\n#\n#    example/test1.sh:tests@shell=bash\n#    example/test1.sh:tests@shell=zsh\n#    example/test2.sh:tests@shell=bash\n#    example/test2.sh:tests@shell=zsh\n#\n# Also creates two `shunit2_tests` target\n# generators, which can be used as aliases\n# to their generated targets:\n#\n#    example:tests@shell=bash\n#    example:tests@shell=zsh\n#\n# Generally, you can still use `example:tests`\n# without the `@` suffix as an alias to all the \n# created targets.\n\nshunit2_tests(\n    name=\"tests\",\n    sources=[\"test1.sh\", \"test2.sh\"],\n    shell=parametrize(\"bash\", \"zsh\"),\n)",
      "language": "python",
      "name": "example/BUILD"
    }
  ]
}
[/block]
You can combine `parametrize` with the ` overrides` field to set more granular metadata for generated targets:
[block:code]
{
  "codes": [
    {
      "code": "# Generates three `shunit2_test` targets:\n#\n#    example/test1.sh:tests\n#    example/test2.sh:tests@shell=bash\n#    example/test2.sh:tests@shell=zsh\n#\n# The `shunit2_tests` target generator\n# `example:tests` can be used as an alias\n# to all 3 created targets.\n\nshunit2_tests(\n    name=\"tests\",\n    sources=[\"test1.sh\", \"test2.sh\"],\n    overrides={\n        \"test2.sh\": {\"shell\": parametrize(\"bash\", \"zsh\")},\n    },\n)",
      "language": "python",
      "name": "example/BUILD"
    }
  ]
}
[/block]