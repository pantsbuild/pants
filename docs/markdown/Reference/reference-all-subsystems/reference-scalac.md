---
title: "scalac"
slug: "reference-scalac"
hidden: false
createdAt: "2022-06-02T21:10:08.977Z"
updatedAt: "2022-06-02T21:10:09.404Z"
---
The Scala compiler.

Backend: <span style="color: purple"><code>pants.backend.experimental.scala</code></span>
Config section: <span style="color: purple"><code>[scalac]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--scalac-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_SCALAC_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to scalac, e.g. `--scalac-args='-encoding UTF-8'`.
</div>
<br>

<div style="color: purple">
  <h3><code>plugins_for_resolve</code></h3>
  <code>--scalac-plugins-for-resolve=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_SCALAC_PLUGINS_FOR_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A dictionary, whose keys are the names of each JVM resolve that requires default `scalac` plugins, and the value is a comma-separated string consisting of scalac plugin names. Each specified plugin must have a corresponding `scalac_plugin` target that specifies that name in either its `plugin_name` field or is the same as its target name.
</div>
<br>


## Advanced options

None

## Deprecated options

None