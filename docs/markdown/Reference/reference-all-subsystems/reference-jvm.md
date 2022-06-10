---
title: "jvm"
slug: "reference-jvm"
hidden: false
createdAt: "2022-06-02T21:09:51.340Z"
updatedAt: "2022-06-02T21:09:51.693Z"
---
Options for general JVM functionality.

JDK strings will be passed directly to Coursier's `--jvm` parameter. Run `cs java --available` to see a list of available JVM versions on your platform.

If the string 'system' is passed, Coursier's `--system-jvm` option will be used instead, but note that this can lead to inconsistent behavior since the JVM version will be whatever happens to be found first on the system's PATH.

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>
Config section: <span style="color: purple"><code>[jvm]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>resolves</code></h3>
  <code>--jvm-resolves=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_JVM_RESOLVES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "jvm-default": "3rdparty/jvm/default.lock"
}</pre></span>

<br>

A dictionary mapping resolve names to the path of their lockfile.
</div>
<br>

<div style="color: purple">
  <h3><code>default_resolve</code></h3>
  <code>--jvm-default-resolve=&lt;str&gt;</code><br>
  <code>PANTS_JVM_DEFAULT_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>jvm-default</code></span>

<br>

The default value used for the `resolve` and `compatible_resolves` fields.

The name must be defined as a resolve in `[jvm].resolves`.
</div>
<br>

<div style="color: purple">
  <h3><code>debug_args</code></h3>
  <code>--jvm-debug-args=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_JVM_DEBUG_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Extra JVM arguments to use when running tests in debug mode.

For example, if you want to attach a remote debugger, use something like ['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>tool_jdk</code></h3>
  <code>--jvm-tool-jdk=&lt;str&gt;</code><br>
  <code>PANTS_JVM_TOOL_JDK</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>temurin:1.11</code></span>

<br>

The JDK to use when building and running Pants' internal JVM support code and other non-compiler tools. See `jvm` help for supported values.
</div>
<br>

<div style="color: purple">
  <h3><code>jdk</code></h3>
  <code>--jvm-jdk=&lt;str&gt;</code><br>
  <code>PANTS_JVM_JDK</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>temurin:1.11</code></span>

<br>

The JDK to use.

This string will be passed directly to Coursier's `--jvm` parameter. Run `cs java --available` to see a list of available JVM versions on your platform.

If the string 'system' is passed, Coursier's `--system-jvm` option will be used instead, but note that this can lead to inconsistent behavior since the JVM version will be whatever happens to be found first on the system's PATH.
</div>
<br>

<div style="color: purple">
  <h3><code>global_options</code></h3>
  <code>--jvm-global-options=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_JVM_GLOBAL_OPTIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

List of JVM options to pass to all JVM processes.

Options set here will be used by any JVM processes required by Pants, with the exception of heap memory settings like `-Xmx`, which need to be set using `[GLOBAL].process_total_child_memory_usage` and `[GLOBAL].process_per_child_memory_usage`.
</div>
<br>


## Deprecated options

None