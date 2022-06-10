---
title: "kotlinc_plugin"
slug: "reference-kotlinc_plugin"
hidden: false
createdAt: "2022-06-02T21:10:38.409Z"
updatedAt: "2022-06-02T21:10:39.014Z"
---
A plugin for `kotlinc`.

To enable a `kotlinc` plugin, define a target with this target type, and set the `artifact` field to the address of a `jvm_artifact` target that provides the plugin. Set the `plugin_id` field to the ID of the plugin if that name cannot be inferred from the `name` of this target.

The standard `kotlinc` plugins are available via the following artifact coordinates and IDs: * All-open: `org.jetbrains.kotlin:kotlin-allopen:VERSION` (ID: `all-open`) * No-arg: `org.jetbrains.kotlin:kotlin-noarg:VERSION` (ID: `no-arg`) * SAM with receiver: `org.jetbrains.kotlin:kotlin-sam-with-receiver:VERSION` (ID: `sam-with-receiver`) * kapt (annotation processor): `org.jetbrains.kotlin:org.jetbrains.kotlin:kotlin-annotation-processing-embeddable:VERSION` (ID: `kapt3`) * Seralization: `org.jetbrains.kotlin:kotlin-serialization:VERSION` (ID: `serialization`)

Backend: <span style="color: purple"><code>pants.backend.experimental.kotlin</code></span>

## <code>artifact</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The address of a `jvm_artifact` that defines a plugin for `kotlinc`.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>plugin_args</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Optional list of argument to pass to the plugin.

## <code>plugin_id</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The ID for `kotlinc` to use when setting options for the plugin.

If not set, the plugin ID defaults to the target name.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.