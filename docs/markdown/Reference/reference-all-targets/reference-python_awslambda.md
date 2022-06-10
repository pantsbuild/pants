---
title: "python_awslambda"
slug: "reference-python_awslambda"
hidden: false
createdAt: "2022-06-02T21:10:44.640Z"
updatedAt: "2022-06-02T21:10:45.107Z"
---
A self-contained Python function suitable for uploading to AWS Lambda.

See [AWS Lambda](doc:awslambda-python).

Backend: <span style="color: purple"><code>pants.backend.awslambda.python</code></span>

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

## <code>handler</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

Entry point to the AWS Lambda handler.

You can specify a full module like 'path.to.module:handler_func' or use a shorthand to specify a file name, using the same syntax as the `sources` field, e.g. 'lambda.py:handler_func'.

You must use the file name shorthand for file arguments to work with this target.

## <code>include_requirements</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

Whether to resolve requirements and include them in the Pex. This is most useful with Lambda Layers to make code uploads smaller when deps are in layers. https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html

## <code>output_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Where the built asset should be located.

If undefined, this will use the path to the BUILD file, followed by the target name. For example, `src/python/project:app` would be `src.python.project/app.ext`.

When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

Warning: setting this value risks naming collisions with other package targets you may have.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[python].resolves` to use.

If not defined, will default to `[python].default_resolve`.

All dependencies must share the same value for their `resolve` field.

## <code>runtime</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The identifier of the AWS Lambda runtime to target (pythonX.Y). See https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.