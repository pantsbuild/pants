---
title: "junit_test"
slug: "reference-junit_test"
hidden: false
createdAt: "2022-06-02T21:10:34.413Z"
updatedAt: "2022-06-02T21:10:34.823Z"
---
A single Java test, run with JUnit.

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>

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

## <code>experimental_provides_types</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Signals that the specified types should be fulfilled by these source files during dependency inference.

This allows for specific types within packages that are otherwise inferred as belonging to `jvm_artifact` targets to be unambiguously inferred as belonging to this first-party source.

If a given type is defined, at least one source file captured by this target must actually provide that symbol.

## <code>jdk</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The major version of the JDK that this target should be built with. If not defined, will default to `[jvm].default_source_jdk`.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[jvm].resolves` to use when compiling this target.

If not defined, will default to `[jvm].default_resolve`.

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