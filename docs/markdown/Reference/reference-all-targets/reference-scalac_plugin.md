---
title: "scalac_plugin"
slug: "reference-scalac_plugin"
hidden: false
createdAt: "2022-06-02T21:10:56.870Z"
updatedAt: "2022-06-02T21:10:57.321Z"
---
A plugin for `scalac`.

Currently only thirdparty plugins are supported. To enable a plugin, define this target type, and set the `artifact=` field to the address of a `jvm_artifact` that provides the plugin.

If the `scalac`-loaded name of the plugin does not match the target's name, additionally set the `plugin_name=` field.

Backend: <span style="color: purple"><code>pants.backend.experimental.scala</code></span>

## <code>artifact</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The address of a `jvm_artifact` that defines a plugin for `scalac`.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>plugin_name</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The name that `scalac` should use to load the plugin.

If not set, the plugin name defaults to the target name.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.