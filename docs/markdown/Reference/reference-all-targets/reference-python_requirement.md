---
title: "python_requirement"
slug: "reference-python_requirement"
hidden: false
createdAt: "2022-06-02T21:10:46.586Z"
updatedAt: "2022-06-02T21:10:47.046Z"
---
A Python requirement installable by pip.

This target is useful when you want to declare Python requirements inline in a BUILD file. If you have a `requirements.txt` file already, you can instead use the target generator `python_requirements` to convert each requirement into a `python_requirement` target automatically. For Poetry, use `poetry_requirements`.

See [Third-party dependencies](doc:python-third-party-dependencies).

Backend: <span style="color: purple"><code>pants.backend.python</code></span>

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

## <code>modules</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The modules this requirement provides (used for dependency inference).

For example, the requirement `setuptools` provides `["setuptools", "pkg_resources", "easy_install"]`.

Usually you can leave this field off. If unspecified, Pants will first look at the default module mapping (https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/dependency_inference/default_module_mapping.py), and then will default to the normalized project name. For example, the requirement `Django` would default to the module `django`.

Mutually exclusive with the `type_stub_modules` field.

## <code>requirements</code>

<span style="color: purple">type: <code>Iterable[str]</code></span>
<span style="color: green">required</span>

A pip-style requirement string, e.g. `["Django==3.2.8"]`.

You can specify multiple requirements for the same project in order to use environment markers, such as `["foo>=1.2,<1.3 ; python_version>'3.6'", "foo==0.9 ; python_version<'3'"]`.

If the requirement depends on some other requirement to work, such as needing `setuptools` to be built, use the `dependencies` field instead.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[python].resolves` that this requirement is included in.

If not defined, will default to `[python].default_resolve`.

When generating a lockfile for a particular resolve via the `generate-lockfiles` goal, it will include all requirements that are declared with that resolve. First-party targets like `python_source` and `pex_binary` then declare which resolve they use via their `resolve` field; so, for your first-party code to use a particular `python_requirement` target, that requirement must be included in the resolve used by that code.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>type_stub_modules</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The modules this requirement provides if the requirement is a type stub (used for dependency inference).

For example, the requirement `types-requests` provides `["requests"]`.

Usually you can leave this field off. If unspecified, Pants will first look at the default module mapping (https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/dependency_inference/default_module_mapping.py). If not found _and_ the requirement name starts with `types-` or `stubs-`, or ends with `-types` or `-stubs`, will default to that requirement name without the prefix/suffix. For example, `types-requests` would default to `requests`. Otherwise, will be treated like a normal requirement (see the `modules` field).

Mutually exclusive with the `modules` field.