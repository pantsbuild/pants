---
title: "scalatest"
slug: "reference-scalatest"
hidden: false
createdAt: "2022-06-02T21:10:10.904Z"
updatedAt: "2022-06-02T21:10:11.390Z"
---
The Scalatest test framework (https://www.scalatest.org/)

Backend: <span style="color: purple"><code>pants.backend.experimental.scala</code></span>
Config section: <span style="color: purple"><code>[scalatest]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--scalatest-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_SCALATEST_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Scalatest, e.g. `--scalatest-args='-t $testname'`.

See https://www.scalatest.org/user_guide/using_the_runner for supported arguments.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--scalatest-version=&lt;str&gt;</code><br>
  <code>PANTS_SCALATEST_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>3.2.10</code></span>

<br>

Version string for the tool. This is available for substitution in the `[scalatest].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--scalatest-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SCALATEST_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "org.scalatest:scalatest&lowbar;2.13:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[scalatest].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--scalatest-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_SCALATEST_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/scala/subsystems/scalatest.default.lockfile.txt for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=scalatest`.
</div>
<br>


## Deprecated options

None