---
title: "kotlinc"
slug: "reference-kotlinc"
hidden: false
createdAt: "2022-06-02T21:09:53.130Z"
updatedAt: "2022-06-02T21:09:53.553Z"
---
The Kotlin programming language (https://kotlinlang.org/).

Backend: <span style="color: purple"><code>pants.backend.experimental.kotlin</code></span>
Config section: <span style="color: purple"><code>[kotlinc]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--kotlinc-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_KOTLINC_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to kotlinc, e.g. `--kotlinc-args='-Werror'`.

See https://kotlinlang.org/docs/compiler-reference.html for supported arguments.
</div>
<br>

<div style="color: purple">
  <h3><code>plugins_for_resolve</code></h3>
  <code>--kotlinc-plugins-for-resolve=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_KOTLINC_PLUGINS_FOR_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A dictionary, whose keys are the names of each JVM resolve that requires default `kotlinc` plugins, and the value is a comma-separated string consisting of kotlinc plugin names. Each specified plugin must have a corresponding `kotlinc_plugin` target that specifies that name in either its `plugin_name` field or is the same as its target name.
</div>
<br>


## Advanced options

None

## Deprecated options

None