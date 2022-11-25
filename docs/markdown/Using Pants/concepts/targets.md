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

Each target type has different _fields_, or individual metadata values. Run `./pants help $target` to see which fields a particular target type has, e.g. `./pants help file`. Most fields are optional and use sensible defaults.

All target types have a `name` field, which is used to identify the target. Target names must be unique within a directory.

You can autoformat `BUILD` files by enabling a `BUILD` file formatter by adding it to `[GLOBAL].backend_packages` in `pants.toml` (such as `pants.backend.build_files.fmt.black` [or others](doc:enabling-backends)). Then to format, run `./pants fmt '**/BUILD'` or `./pants fmt ::` (formats everything).

Target addresses
================

A target is identified by its unique address, in the form `path/to/dir:name`. The above example has the addresses `helloworld/greet:tests` and `helloworld/greet:bin`.

Addresses are used in the `dependencies` field to depend on other targets. Addresses can also be used as command-line arguments, such as `./pants fmt path/to:tgt`.

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
> Addressed defined in the `BUILD` file at the root of your repository are prefixed with `//`, e.g. `//:my_tgt`.

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
> - File arguments will run over all owning targets, e.g. `./pants test path/to/test.ext` would run both test targets as two separate subprocesses, even though you might only expect a single subprocess.
> - Pants will sometimes no longer be able to infer dependencies on this file because it cannot disambiguate which of the targets you want to use. You must use explicit dependencies instead. (For some blessed fields, like the `resolve` field, if the targets have different values, then there will not be ambiguity.)
>
> You can run `./pants list path/to/file.ext` to see all "owning" targets to check if >1 target has the file in its `source` field.

`dependencies` field
====================

A target's dependencies determines which other first-party code and third-party requirements to include when building the target.

Usually, you leave off the `dependencies` field thanks to _dependency inference_. Pants will read your import statements and map those imports back to your first-party code and your third-party requirements. You can run `./pants dependencies path/to:target` to see what dependencies Pants infers.

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
> If you don't like that Pants inferred a certain dependency—as reported by [`./pants dependencies path/to:tgt`](doc:project-introspection)—tell Pants to ignore it with `!`:
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
> Transitive excludes can only be used in target types that conventionally are not dependend upon by other targets, such as `pex_binary` and `python_test` / `python_tests`. This is meant to limit confusion, as using `!!` in something like a `python_source` / `python_sources` target could result in surprising behavior for everything that depends on it. (Pants will print a helpful error when using `!!` when it's not legal.)

Field default values
====================

As mentioned above in [BUILD files](doc:targets#build-files), most fields use sensible defaults. And for specific cases it is easy to provide some other value to a specific target. The issue is if you  want to apply a specific non-default value for a field on many targets. This can get unwieldy, error  prone and hard to maintain. Enter `__defaults__`.

Default field values per target are set using the `__defaults__` BUILD file symbol, and apply to the current subtree.

The defaults are provided as a dictionary mapping targets to the default field values. Multiple targets may share the same set of default field values, when grouped together in parenthesis (as a Python tuple).

Use the `all` keyword argument to provide default field values that should apply to all targets.

The `extend=True` keyword argument allows to add to any existing default field values set by a previous `__defaults__` call rather than replacing them.

Default fields and values are validated against their target types, except when provided using the `all` keyword, in which case only values for fields applicable to each target are validated.

This means, that it is legal to provide a default value for `all` targets, even if it is only a subset of targets that actually supports that particular field.

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

Target generation
=================

To reduce boilerplate, Pants provides target types that generate other targets. For example:

- `files` -> `file`
- `python_tests` -> `python_test`
- `go_mod` -> `go_third_party_package`

Usually, prefer these target generators. [`./pants tailor ::`](doc:initial-configuration#5-generate-build-files) will automatically add them for you.

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
    "1-1": "`path/to:tgt_generator#generated_name`  \n  \nExample: `3rdparty/py:reqs#django`  \n  \nRun `./pants help $target_type` on the target generator to see how it sets the generated name. For example, `go_mod` uses the Go package's name.  \n  \nIf the target generator left off the `name` field, you can leave it off for the generated address too, e.g. `3rdparty/py#django` (without the `:reqs` portion).  \n  \nWith the `dependencies` field, you can use relative addresses to reference generated targets in the same BUILD file, e.g. `:generator#generated_name` instead of `src/py:generated#generated_name`. If the target generator uses the default `name`, you can simply use `#generated_name`."
  },
  "cols": 2,
  "rows": 2,
  "align": [
    "left",
    "left"
  ]
}
[/block]

Run [`./pants list dir:`](doc:project-introspection) in the directory of the target generator to see all generated target addresses, and [`./pants peek dir:`](doc:project-introspection) to see all their metadata.

You can use the address for the target generator as an alias for all of its generated targets. For example, if you have the `files` target `assets:logos`, adding `dependencies=["assets:logos"]`to another target will add a dependency on each generated `file` target. Likewise, if you have a `python_tests` target `project:tests`, then `./pants test project:tests` will run on each generated `python_test` target.

> 📘 Tip: one BUILD file per directory
>
> Target generation means that it is technically possible to put everything in a single BUILD file.
>
> However, we've found that it usually scales much better to use a single BUILD file per directory. Even if you start with using the defaults for everything, projects usually need to change some metadata over time, like adding a `timeout` to a test file or adding `dependencies` on resources.
>
> It's useful for metadata to be as fine-grained as feasible, such as by using the `overrides` field to only change the files you need to. Fine-grained metadata is key to having smaller cache keys (resulting in more cache hits), and allows you to more accurately reflect the status of your project. We have found that using one BUILD file per directory encourages fine-grained metadata by defining the metadata adjacent to where the code lives.
>
> [`./pants tailor ::`](doc:initial-configuration#5-generate-build-files) will automatically create targets that only apply metadata for the directory.

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
    interpreter_constraints=parametrize(py2=["==2.7.*"], py3=[">=3.6"]),
    resolve=parametrize("lock-a", "lock-b"),
)
```

The targets' addresses will have `@key=value` at the end, as shown above. Run [`./pants list dir:`](doc:project-introspection) in the directory of the parametrized target to see all parametrized target addresses, and [`./pants peek dir:`](doc:project-introspection) to see all their metadata.

Generally, you can use the address without the `@` suffix as an alias to all the parametrized targets. For example, `./pants test example:tests` will run all the targets in parallel. Use the more precise address if you only want to use one parameter value, e.g. `./pants test example:tests@shell=bash`.

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

You can combine `parametrize` with the ` overrides` field to set more granular metadata for generated targets:

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

Visibility
==========

Visibility rules are the mechanism by which to control who may depend on whom. It is an implementation of Pants's dependency rules API. Using file globs this may be set from entire directory trees down to single files. Targets may be selected not only by its file path but also by target type and tags.

To use the visibility feature, enable the `pants.backend.visibility` backend by adding it to the list of `backend_packages` in the `[GLOBAL]` section of your `pants.toml` file.

```toml
[GLOBAL]
backend_packages.add = [
  ...
  "pants.backend.experimental.visibility",
]

```

> 📘 The visibility implementation is marked "experimental"
>
> This does not mean you should not use it, only that it is in "preview" mode meaning that things may change between releases without following our deprecation policy as we work on stabilizing this feature. See [the stabilization ticket](https://github.com/pantsbuild/pants/issues/17634) for what remains to be done for the visibility backend to graduate out of preview.


Dependencies and dependents
---------------------------

The visibility rules operates on the dependency link between two targets. Dependencies are directional, so if target `A` depends on another target `B` the dependency goes from the "origin" target `A` -> `B`, we say that `B` is the __dependency__ of `A`, while `A` is the __dependent__ of `B`.

> 📘 The Direction of Dependency, `A` -> `B`.
>
> Target `A` may have zero or more dependencies. For each of those dependencies `A` is their dependent.
>
> Target `B` may be the dependency of zero or more dependents. For each of those dependents `B` is their dependency.

Dependency rules are configured in the BUILD files along with targets and any other BUILD file configuration. Rules may be provided on either end of a dependency link between two targets. There are two different keywords to use, one for each side of this link. As discussed above, any target may have both dependencies and dependents and these keywords map onto that:

* `__dependencies_rules__` declares the rules that applies to a targets dependencies.
* `__dependents_rules__` declares the rules that applies to a targets dependents.


    `A` `__dependencies_rules__` -> `__dependents_rules__` `B` `__dependencies_rules__` -> ...


For each dependency there may be up to 2 sets of rules consulted to determine if it should be `allowed` or `denied` (or just `warn`, see [Rule Actions](doc:targets#rule-actions)), one for each end of the dependency link. The rules themselves are merely [path globs](doc:targets#glob-syntax) applied in order until a matching rule is found. It is an error for there to not be any matching rule, if any rules are defined. That is, you may have a dependency without any rules and that will be allowed, but as soon as there are rules in play there must exist at least one that is a match for the dependency link that dictates the outcome.

> 🚧 There are no default rules
>
> When you setup a set of rules, it must be comprehensive or Pants will throw an error when it fails to find a matching rule for a dependency/dependent.
>
> There is a default behaviour in the absence of any rules however, in which case all dependencies will be allowed.
> That is, as you enable the visibility backend, you may incrementally start to introduce rules in your project there is no need to cover everything with rules up-front.
>
> **Rule sets do propagate to their subtrees unless overidden with new rule sets in a corresponding BUILD file.**

Lets look at another dependency example, where we have the following BUILD files for the two source files `src/a/main.py` and `src/b/lib.py`:

```python
# src/a/BUILD
python_sources(dependencies=["src/b/lib.py"], tags=["apps"])

# src/b/BUILD
python_sources(tags=["libs"])
```

The dependency `src/a/main.py` -> `src/b/lib.py` would consult the `__dependencies_rules__` in `src/a/BUILD` for a rule that matches `src/b/lib.py` and the `__dependents_rules__` in `src/b/BUILD` for a rule that matches `src/a/main.py`. See [rule sets](doc:targets#rule-sets) for more details on how this works.

When declaring your rules, you not only provide the rules for the current directory, but also set the default rules for all the subdirectories as well. When overriding such default rules in a child BUILD file, there is a `extend=True` kwarg you may use if you want the default rules to still apply after the ones declared in the current BUILD file.

```python
# BUILD
__dependencies_rules__(
  <ruleset-top-1>,
  <ruleset-top-2>,
)

# src/nested/BUILD
# The following is equivalent:
__dependencies_rules__(
  <ruleset-nested-1>,
  <ruleset-nested-2>,
  <ruleset-top-1>,
  <ruleset-top-2>,
)
# with:
__dependencies_rules__(
  <ruleset-nested-1>,
  <ruleset-nested-2>,
  extend=True,
)
```


Rule sets
---------

As there may be many targets and files with dependencies, odds are that they won't all share the same set of rules. The rules keywords accepts multiple sets of rules, or "rule sets", along with "selector rules" that is used to select which set to use for each target.

The overall structure is (example with 2 rule sets):

```python
# BUILD

__dependencies_rules__(

  # Rule set 1
  (<selectors>, <rule a>, <rule b>, ...),

  # Rule set 2
  (<selectors>, <rules>, ...),

  ...
)
```

The rules are just string values using a [glob syntax](doc:targets#glob-syntax) for pattern matching and may be grouped together for readability (how rules are grouped does not affect how they are applied). The selector is a dictionary value with properties describing what targets its associated rules apply to and together this pair of selector(s) and rules is called a __rule set__. A rule set may have multiple selectors wrapped in a list/tuple.

The selector has three properties: `type`, `tags` and `path`. From the above example, when determining which rule set to apply for the dependencies of `src/a/main.py` Pants will look for the first selector for `src/a/BUILD` that satisifies the properties `type=python_sources`, `tags=["apps"]` and `path=src/a/main.py`. The selection is based on exclusion so only when there is a property value and it doesn't match the targets property it will move on to the next selector, so the lack of a property will be considered to match anything. Consequently an empty selector matches all targets.

The values of a selector supports wildcard patterns (or globs) in order to have a single selector match multiple different targets. The `path` property uses the same [glob syntax](doc:targets#glob-syntax) as the rules, while `type` and `tags` use a simpler one described below. When listing multiple values for the `tags` property, the target must have all of them in order to match. Spread the tags over multiple selectors in order to switch from AND to OR as required. The target `type` to match against will be that of the type used in the BUILD file, as the path (and target address) may refer to a generated target it is the target generators type that will be used during the selector matching process.

The simpler glob syntax used by the `type` and `tags` selector values supports `*` as a match anything and is otherwise case sensitive. (implementation detail: it relies on the `fnmatch` python library so there is a bit more syntax available, but if you find yourself using more than `*` please let us know in case we switch to something else).

### NOTE/TODO: maybe drop the use of `fnmatch` entirely, as supporting just `*` is real easy.

The selectors are matched against the target in the order they are defined in the BUILD file, and the first rule set with a selector that is a match will be selected. The rules from the selected rule set is then matched in order against the path of the **target on the other end** of the dependency link. This is worth reading again; Using the above example again, the rules defined in `src/a/BUILD` will be matched against `src/b/lib.py` while the `path` selector will be matched against `src/a/main.py`.

Providing some example rule sets for the above example (see [rule actions](doc:targets#rule-actions) on how to mark a rule as "allow" or "deny"):

```python
# src/a/BUILD  (continued from previous example)
__dependencies_rules__(
  (
    {"type": python_sources},  # We can use the target type unquoted when we don't need glob syntax
    "src/a/**",  # May depend on anything from src/a/
    "src/b/lib.py",  # May depend on specific file
    "!*",  # May not depend on anything else. This is our "catch all" rule, ensuring there will never be any fall-through, which would've been an error
  ),

  # We need another rule set, in case we have non-python sources in here, to avoid fall-through.
  # Sticking in a generic catch-all allow-all rule.
  ({}, "*"),
)


# src/b/BUILD  (continued from previous example)
__dependents_rules__(
  (
    (  # Using multiple selectors
      {"type": "python_*", "tags":["any-python"]},
      {"type": "*", "tags":["libs"]},
      {"path": "special-cased.py"}
    ),
    (  # Grouping rules for readability
      (  # Deny rules
        "!tests/**",  # No tests
        "!src/*/*/**", # Nothing deeply nested
      ),
      (  # Allow rules
        "*",  # Allow everything else
      ),
    )
  ),

  # We need another rule set, in case we have non-python sources in here, to avoid fall-through.
  # Sticking in a generic catch-all allow-all rule.
  ({}, "*"),
)
```

There are some syntactic sugar for selectors so they may be declared in a more concise text form rather than as a dictionary (this is also the form on which they are presented in messages from Pants, when possible). The syntax is `<type>(<tags>, ...)[<path>]`. With all parts optional, so `""` is a valid catch-all selector. Providing all the selectors from the previous example code block in string form for reference:
```python
python_sources  # {"type": python_sources}  -- target types works as strings when used bare
"python_*(any-python)"  # {"type": "python_*", "tags":["any-python"]}
"*(libs)"  # {"type": "*", "tags":["libs"]}
"[special-cased.py]"  # {"path": "special-cased.py"}
```

Glob syntax
-----------

The visibility rules support a basic glob syntax, using `*` as a match anything non-recursively with the `**` variant being for a recursive match anything. All rules are matched until the end of the path it is being applied to, so if there is not trailing wildcard (`*` or `**`) the end of the rule glob will match the end of the path. This allows for matching on file types/names regardless of where in the project tree they are:
```
.py
my_source.py
my_*.py
```

Any leading wildcards may be used to emphasize this if desired, but will function the same, so the above is equvalent to (non-exhaustive list of alternatives):
```
*.py
*/my_source.py
*/my_*.py

**/*.py
**/*my_source.py
**/*my_*.py
```

When providing a file name, like `my_source.py` it will be assumed that it will be the full name, so `another_my_source.py` will _not_ be considered a match in that case.

To match any file in a particular directory:
```
some/directory/*
```

So far the rule globs have been matched from anywhere in the matched to path up to the end. To ensure the path begins with a certain pattern we'd have to provide full paths in our rules, like `src/python/proj/lib/file.py` if we want to make sure that our `file.py` is from the `src/` tree. To avoid lengthy and rigid rule globs hurting refactorings etc, there's a concept of "anchoring" the rule. That will apply the rule glob from a fixed point in the matched to path, and there are three such points: project root, rule declaration path and rule invocation path. The difference between declaration and invocation is explained below.

#### Anchoring mode

The glob prefix specifies which "anchoring mode" to use, and are:

- `//` - Anchor the glob to the project root.
  Example: `//src/python/**` will match all files from the `src/python/` tree.

- `/` - Anchor the glob to the declaration path.
  This is the path of the BUILD file where the rule is declared, using one of the rules keywords (i.e. `__dependencies_rules__` or `__dependents_rules__`)
  Example: in `src/python/BUILD` there is a rule `/proj/**` which will match all files from the `src/python/proj/` tree.

- `.` - Anchor the glob to the invocation path.
  This is the file path of the target for which the rule will apply for. Relative paths are supported, so `../../cousin/path` is valid.
  Example: there is a rule `./lib/*` when applied for the file `src/python/proj/main.py` it would match `src/python/proj/lib/*`.

- Any other value will be left "floating" as described at the top of this glob syntax chapter.

> 🚧 Regardless of anchoring mode, all rules are always anchored to the end of the matched path.

Rule actions
------------

When a matching rule is found for a path, the path is either allowed or denied based on the rule's action. The dependency link as a whole is only allowed if both ends of the dependency allow it. By default a rule's action is `ALLOW`, but may be changed to `DENY` or `WARN`. The `WARN` action logs a warning message rather than raising an error, but will otherwise allow the dependency.

The rule action is specified as a prefix on the rule glob:

- `!` - Sets the rule's action to `DENY`.
- `?` - Sets the rule's action to `WARN`.
- Any other value is part of the [rule glob](doc:targets#glob-syntax).
