---
title: "go_package"
slug: "reference-go_package"
hidden: false
createdAt: "2022-06-02T21:10:28.557Z"
updatedAt: "2022-06-02T21:10:28.981Z"
---
A first-party Go package (corresponding to a directory with `.go` files).

Expects that there is a `go_mod` target in its directory or in an ancestor directory.

Backend: <span style="color: purple"><code>pants.backend.experimental.go</code></span>

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

## <code>skip_gofmt</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.go</code></span>

If true, don't run gofmt on this package.

## <code>skip_tests</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, don't run this package's tests.

## <code>sources</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>(&#x27;&ast;.go&#x27;, &#x27;&ast;.s&#x27;)</code></span>

A list of files and globs that belong to this target.

Paths are relative to the BUILD file's directory. You can ignore files/globs by prefixing them with `!`.

Example: `sources=['example.ext', 'test_*.ext', '!test_ignore.ext']`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>test_timeout</code>

<span style="color: purple">type: <code>int | None</code></span>
<span style="color: green">default: <code>None</code></span>

A timeout (in seconds) when running this package's tests.

If this field is not set, the test will never time out.