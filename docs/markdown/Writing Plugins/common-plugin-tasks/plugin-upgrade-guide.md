---
title: "Plugin upgrade guide"
slug: "plugin-upgrade-guide"
excerpt: "How to adjust for changes made to the Plugin API."
hidden: false
createdAt: "2020-10-12T16:19:01.543Z"
updatedAt: "2022-04-27T20:02:17.695Z"
---
2.12
----

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.12.x.md> for the changelog.

### Unified formatters

Formatters no longer need to be installed in both the `FmtRequest` and `LintTargetsRequest` `@unions`: instead, installing in the `FmtRequest` union is sufficient to act as both a linter and formatter.

See [Add a formatter](doc:plugins-fmt-goal) for more information.

2.11
----

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.11.x.md> for the changelog.

### Deprecated `Subsystem.register_options()`

Pants 2.11 added "concrete" option types which when used as class attributes of your subsystem. These are more declarative, simplify accessing options, and work with MyPy!

Before:

```python
class MySubsystem(Subsystem):
    options_scope = "example"
    help = "..."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--my-opt",
            type=bool,
            default=True,
            help="...",
        )
```

Now:

```python
class MySubsystem(Subsystem):
    options_scope = "example"
    help = "..."

    my_opt = BoolOption(
        "--my-opt",
        default=True,
        help="...",
    )
```

To access an option in rules, simply use `my_subsystem.my_opt` rather than `my_subsystem.options.my_opt`.

See [Options and subsystems](doc:rules-api-subsystems) for more information, including the available types.

### Moved `BinaryPathRequest` to `pants.core.util_rules.system_binaries`

The new module `pants.core.util_rules.system_binaries` centralizes all discovery of existing binaries on a user's machines.

The functionality is the same, you only need to change your imports for types like `BinaryPathRequest` to `pants.core.util_rules.system_binaries` rather than `pants.engine.process`.

### Deprecated not implementing `TargetGenerator` in `GenerateTargetsRequest` implementors

See <https://github.com/pantsbuild/pants/pull/14962> for an explanation and some examples of how to fix.

### Replaced `GoalSubsystem.required_union_implementations` with `GoalSubsystem.activated()`

See <https://github.com/pantsbuild/pants/pull/14313> for an explanation and some examples of how to fix.

2.10
----

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.10.x.md> for the changelog.

### Rename `LintRequest` to `LintTargetsRequest`

Pants 2.10 added a new `LintFilesRequest`, which allows you to run linters on code without any owning targets! <https://github.com/pantsbuild/pants/pull/14102>

To improve clarity, we renamed `LintRequest` to `LintTargetsRequest`.

### `FmtRequest`, `CheckRequest`, and `LintTargetsRequest` must set `name`

You must set the class property `name` on these three types.

Before:

```python
class MyPyRequest(CheckRequest):
    field_set_type = MyPyFieldSet
```

After:

```python
class MyPyRequest(CheckRequest):
    field_set_type = MyPyFieldSet
    name = "mypy"
```

This change is what allowed us to add the `lint --only=flake8` feature.

For DRY, it is a good idea to change the `formatter_name`, `linter_name`, and `checker_name` in `FmtResult`, `LintResults`, and `CheckResults`, respectively, to use `request.name` rather than hardcoding the string again. See <https://github.com/pantsbuild/pants/pull/14304> for examples.

### Removed `LanguageFmtTargets` for `fmt`

When setting up a new language to be formatted, you used to have to copy and paste a lot of boilerplate like `ShellFmtTargets`. That's been fixed, thanks to <https://github.com/pantsbuild/pants/pull/14166>.

To fix your code:

1. If you defined any new languages to be formatted, delete the copy-and-pasted `LanguageFmtTargets` code.
2. For every formatter, change the `UnionRule` to be `UnionRule(FmtRequest, BlackRequest)`, rather than `UnionRule(PythonFmtRequest, BlackRequest)`, for example.

### `ReplImplementation` now passes root targets, not transitive closure

We realized that it's useful to let REPL rules know what was specified vs. what is a transitive dependency: <https://github.com/pantsbuild/pants/pull/14323>.

To adapt to this, you will want to use `transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses)`, then operate on `transitive_targets.closure`.

### Removed `PexFromTargetsRequest.additional_requirements`

Let us know if you were using this, and we can figure out how to add it back: <https://github.com/pantsbuild/pants/pull/14350>.

### Removed `PexFromTargetsRequest(direct_deps_only: bool)`

Let us know if you were using this, and we can figure out how to add it back: <https://github.com/pantsbuild/pants/pull/14291>.

### Renamed `GenerateToolLockfileSentinel.options_scope` to `resolve_name`

See <https://github.com/pantsbuild/pants/pull/14231> for more info.

### Renamed `PythonModule` to `PythonModuleOwnersRequest`

This type was used to determine the owners of a Python module. The new name makes that more clear. See <https://github.com/pantsbuild/pants/pull/14276>.

2.9
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.9.x.md> for the changelog.

### Deprecated `RuleRunner.create_files()`, `.create_file()` and `.add_to_build_file()`

Instead, for your `RuleRunner` tests, use `.write_files()`. See <https://github.com/pantsbuild/pants/pull/13817> for some examples.

2.8
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.8.x.md> for the changelog.

### Target modeling changes

Pants 2.8 cleaned up the modeling of targets. Now, there are targets that describe the atom of each language, like `python_test` and `python_source` which correspond to a single file. There are also target generators which exist solely for less boilerplate, like `python_tests` and `python_sources`.

We recommend re-reading [Targets and BUILD files](doc:targets).

#### `SourcesField`

The `Sources` class was replaced with `SourcesField`, `SingleSourceField`, and `MultipleSourcesField`.

When defining new target types with the Target API, you should choose between subclassing `SingleSourceField` and `MultipleSourcesField`, depending on if you want the field to be `source: str` or `sources: list[str]`.

Wherever you were using `Sources` in your `@rule`s, simply replace with `SourcesField`.

#### Renames of some `Sources` subclasses

You should update all references to these classes in your `@rule`s.

- `FilesSources` -> `FileSourceField`
- `ResourcesSources` -> `ResourceSourceField`
- `PythonSources` -> `PythonSourceField`

### `OutputPathField.value_or_default()`

The method `OutputPathField.value_or_default()` no longer takes `Address` as an argument.

2.7
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.7.x.md> for the changelog.

### Type hints work properly

Pants was not using PEP 561 properly, which means that MyPy would not enforce type hints when using Pants APIs. Oops! This is now fixed.

### Options scopes should not have `_`

For example, use `my-subsystem` instead of `my_subsystem`. This is to avoid ambiguity with target types.

2.6
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.6.x.md> for the changelog.

### `ProcessCacheScope`

`ProcessCacheScope.NEVER` was renamed to `ProcessCacheScope.PER_SESSION` to better reflect that a rule never runs more than once in a session (i.e. a single Pants run) given the same inputs.

`ProcessCacheScope.PER_RESTART` was replaced with `ProcessCacheScope.PER_RESTART_ALWAYS` and `ProcessCacheScope.PER_RESTART_SUCCESSFUL`.

### `PexInterpreterConstraints`

Now called `InterpreterConstraints` and defined in `pants.backend.python.util_rules.interpreter_constraints`.

2.5
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.5.x.md> for the changelog.

### `TriBoolField`

`BoolField.value` is no longer `bool | None`, but simply `bool`. This means that you must either set `required = True` or set the `default`.

Use `TriBoolField` if you still want to be able to represent a trinary state: `False`, `True`, and `None`.

### Added `RuleRunner.write_files()`

This is a more declarative way to set up files than the older API of `RuleRunner.create_file()`, `.create_files()`, and `.add_to_build_files()`. See [Testing plugins](doc:rules-api-testing).

2.4
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.4.x.md> for the changelog. 

### `PexRequest` changes how entry point is set

See <https://github.com/pantsbuild/pants/pull/11620>. Instead of setting `entry_point="pytest"` in the `PexRequest` constructor, now you set `main=ConsoleScript("black")` or `main=EntryPoint("pytest")`.

### Must use `EnvironmentRequest` for accessing environment variables

See <https://github.com/pantsbuild/pants/pull/11641>. Pants now eagerly purges environment variables from the run, so using `os.environ` in plugins won't work anymore.

Instead, use `await Get(Environment, EnvironmentRequest(["MY_ENV_VAR"])`. 

For `RuleRunner` tests, you must now either set `env` or the new `env_inherit` arguments for environment variables to be set. Tests are now hermetic.

2.3
---

There were no substantial changes to the Plugin API in 2.3. See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.3.x.md> for the changelog. 

2.2
---

See <https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.2.x.md> for the changelog.

### `PrimitiveField` and `AsyncField` are removed (2.2.0.dev0)

Rather than subclassing `PrimitiveField`, subclass `Field` directly. `Field` now behaves like `PrimitiveField` used to, and `PrimitiveField` was removed for simplicity.

Rather than subclassing `AsyncField` or `AsyncStringSequenceField`, subclass `Field` or a template like `StringField` and also subclass `AsyncFieldMixin`:

```python
from pants.engine.target import AsyncFieldMixin, StringField)

class MyField(StringField, AsyncFieldMixin):
    alias = "my_field"
    help = "Description."
```

Async fields now access the raw value with the property `.value`, rather than `.sanitized_raw_value`. To override the eager validation, override `compute_value()`, rather than `sanitize_raw_value()`. Both these changes bring async fields into alignment with non-async fields.

### Set the property `help` with Subsystems, Targets, and Fields (2.2.0.dev3)

Previously, you were supposed to set the class's docstring for the `./pants help` message. Instead, now set a class property `help`, like this:

```python
class MyField(StringField):
    alias = "my_field"
    help = "A summary.\n\nOptional extra information."
```

Pants will now properly wrap strings and preserve newlines. You may want to run `./pants help ${target/subsystem}` to verify things render properly.

2.1
---

See <https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.1.x.rst> for the changelog.

### `SourcesSnapshot` is now `SpecsSnapshot` (2.1.0rc0)

The type was renamed for clarity. Still import it from `pants.engine.fs`.

2.0
---

See <https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.0.x.rst> for the changelog.

### Use `TransitiveTargetsRequest` as input for resolving `TransitiveTargets` (2.0.0rc0)

Rather than `await Get(TransitiveTargets, Addresses([addr1]))`, use `await Get(TransitiveTargets, TransitiveTargetsRequest([addr1]))`, from `pants.engine.target`.

It's no longer possible to include `TransitiveTargets` in your `@rule` signature in order to get the transitive closure of what the user specified on the command. Instead, put `Addresses` in your rule's signature, and use `await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))`.

### Codegen implementations: use `DependenciesRequestLite` and `TransitiveTargetsLite` (2.0.0rc0)

Due to a new cycle in the rule graph, for any codegen implementations, you must use `DependenciesRequestLite` instead of `DependenciesRequest`, and `TransitiveTargetsLite` instead of `TransitiveTargetsRequest`. Both imports are still from `pants.engine.target`.

These behave identically, except that they do not include dependency inference in the results. Unless you are generating for `input = PythonSources`, this should be fine, as dependency inference is currently only used with Python.

This is tracked by <https://github.com/pantsbuild/pants/issues/10917>.

### Dependencies-like fields have more robust support (2.0.0rc0)

If you have any custom fields that act like the dependencies field, but do not subclass `Dependencies`, there are two new mechanisms for better support.

1. Instead of subclassing `StringSequenceField`, subclass `SpecialCasedDependencies` from `pants.engine.target`. This will ensure that the dependencies show up with `./pants dependencies` and `./pants dependees`.
2. You can use `UnparsedAddressInputs` from `pants.engine.addresses` to resolve the addresses:

```python
from pants.engine.addresses import Address, Addresses, UnparsedAddressedInputs
from pants.engine.target import Targets

...

addresses = await Get(Addresses, UnparsedAddressedInputs(["//:addr1", "project/addr2"], owning_address=None)

# Or, use this.
targets = await Get(
    Targets,
    UnparsedAddressedInputs(["//:addr1", "project/addr2"], owning_address=Address("project", target_name="original")
)
```

If you defined a subclass of `SpecialCasedDependencies`, you can use `await Get(Addresses | Targets, UnparsedAddressInputs, my_tgt[MyField].to_unparsed_address_inputs())`.

(Why would you ever do this? If you have dependencies that you don't treat like normal—e.g. that you will call the equivalent of `./pants package` on those deps—it's often helpful to call out this magic through a dedicated field. For example, Pants's [archive](https://github.com/pantsbuild/pants/blob/969c8dcba6eda0c939918b3bc5157ca45099b4d1/src/python/pants/core/target_types.py#L231-L257) target type has the fields `files` and `packages`, rather than `dependencies`.)

### `package` implementations may want to add the field `output_path` (2.0.0rc0)

All of Pants's target types that can be built via `./pants package` now have an `output_path` field, which allows the user to override the path used for the created asset.

You optionally may want to add this `output_path` field to your custom target type for consistency:

1. Include `OutputPathField` from `pants.core.goals.package` in your target's `core_fields` class property.
2. In your `PackageFieldSet` subclass, include `output_path: OutputPathField`.
3. When computing the filename in your rule, use `my_package_field_set.output_path.value_or_default(field_set.address, file_ending="my_ext")`.
