---
title: "protobuf_source"
slug: "reference-protobuf_source"
hidden: false
createdAt: "2022-06-02T21:10:42.730Z"
updatedAt: "2022-06-02T21:10:43.157Z"
---
A single Protobuf file used to generate various languages.

See language-specific docs:     Python: [Protobuf and gRPC](doc:protobuf-python)
    Go: [Protobuf](doc:protobuf-go)

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.python</code></span>

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

## <code>grpc</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

Whether to generate gRPC code or not.

## <code>jvm_jdk</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.codegen.protobuf.java</code></span>

The major version of the JDK that this target should be built with. If not defined, will default to `[jvm].default_source_jdk`.

## <code>jvm_resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.codegen.protobuf.java</code></span>

The resolve from `[jvm].resolves` to use when compiling this target.

If not defined, will default to `[jvm].default_resolve`.

## <code>python_interpreter_constraints</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.protobuf.python</code></span>

The Python interpreters this code is compatible with.

Each element should be written in pip-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`. You can leave off `CPython` as a shorthand, e.g. `>=2.7` will be expanded to `CPython>=2.7`.

Specify more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']` means either PyPy 3.7 _or_ CPython 3.7.

If the field is not set, it will default to the option `[python].interpreter_constraints`.

See [Interpreter compatibility](doc:python-interpreter-compatibility) for how these interpreter constraints are merged with the constraints of dependencies.

## <code>python_resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.protobuf.python</code></span>

The resolve from `[python].resolves` to use.

If not defined, will default to `[python].default_resolve`.

All dependencies must share the same value for their `resolve` field.

## <code>python_source_root</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.protobuf.python</code></span>

The source root to generate Python sources under.

If unspecified, the source root the `protobuf_sources` is under will be used.

## <code>skip_buf_format</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.protobuf.lint.buf</code></span>

If true, don't run `buf format` on this target's code.

## <code>skip_buf_lint</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.codegen.protobuf.lint.buf</code></span>

If true, don't run `buf lint` on this target's code.

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