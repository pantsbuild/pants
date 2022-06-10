---
title: "pants_requirements"
slug: "reference-pants_requirements"
hidden: false
createdAt: "2022-06-02T21:10:39.217Z"
updatedAt: "2022-06-02T21:10:39.800Z"
---
Generate `python_requirement` targets for Pants itself to use with Pants plugins.

This is useful when writing plugins so that you can build and test your plugin using Pants. The generated targets will have the correct version based on the `version` in your `pants.toml`, and they will work with dependency inference.

Because the Plugin API is not yet stable, the version is set automatically for you to improve stability. If you're currently using a dev release, the version will be set to that exact dev release. If you're using an alpha release, release candidate (rc), or stable release, the version will allow any non-dev-release release within the release series, e.g. `>=2.12.0rc0,<2.13`.

(If this versioning scheme does not work for you, you can directly create `python_requirement` targets for `pantsbuild.pants` and `pantsbuild.pants.testutil`. We also invite you to share your ideas at https://github.com/pantsbuild/pants/issues/new/choose)

Backend: <span style="color: purple"><code>pants.backend.plugin_development</code></span>

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

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

## <code>testutil</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

If true, include `pantsbuild.pants.testutil` to write tests for your plugin.