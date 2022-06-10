---
title: "junit"
slug: "reference-junit"
hidden: false
createdAt: "2022-06-02T21:09:50.613Z"
updatedAt: "2022-06-02T21:09:51.129Z"
---
The JUnit test framework (https://junit.org)

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>
Config section: <span style="color: purple"><code>[junit]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--junit-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_JUNIT_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to JUnit, e.g. `--junit-args='--disable-ansi-colors'`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--junit-version=&lt;str&gt;</code><br>
  <code>PANTS_JUNIT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>5.7.2</code></span>

<br>

Version string for the tool. This is available for substitution in the `[junit].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--junit-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_JUNIT_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "org.junit.platform:junit-platform-console:1.7.2",
  "org.junit.jupiter:junit-jupiter-engine:{version}",
  "org.junit.vintage:junit-vintage-engine:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[junit].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--junit-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_JUNIT_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/jvm/test/junit.default.lockfile.txt for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=junit`.
</div>
<br>


## Deprecated options

None