---
title: "thrift_source"
slug: "reference-thrift_source"
hidden: false
createdAt: "2022-06-02T21:11:03.403Z"
updatedAt: "2022-06-02T21:11:04.308Z"
---
A single Thrift file used to generate various languages.

See language-specific docs:     Python: [Thrift](doc:thrift-python)

Backend: <span style="color: purple"><code>pants.backend.codegen.thrift.apache.python</code></span>

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

## <code>python_resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.thrift.apache.python</code></span>

The resolve from `[python].resolves` to use.

If not defined, will default to `[python].default_resolve`.

All dependencies must share the same value for their `resolve` field.

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