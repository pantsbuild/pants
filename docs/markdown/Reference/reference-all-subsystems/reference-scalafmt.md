---
title: "scalafmt"
slug: "reference-scalafmt"
hidden: false
createdAt: "2022-06-02T21:10:09.612Z"
updatedAt: "2022-06-02T21:10:10.066Z"
---
scalafmt (https://scalameta.org/scalafmt/)

Backend: <span style="color: purple"><code>pants.backend.experimental.scala.lint.scalafmt</code></span>
Config section: <span style="color: purple"><code>[scalafmt]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]scalafmt-skip</code><br>
  <code>PANTS_SCALAFMT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use scalafmt when running `./pants fmt` and `./pants lint`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--scalafmt-version=&lt;str&gt;</code><br>
  <code>PANTS_SCALAFMT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>3.2.1</code></span>

<br>

Version string for the tool. This is available for substitution in the `[scalafmt].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--scalafmt-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SCALAFMT_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "org.scalameta:scalafmt-cli&lowbar;2.13:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[scalafmt].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--scalafmt-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_SCALAFMT_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/scala/lint/scalafmt/scalafmt.default.lockfile.txt for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=scalafmt`.
</div>
<br>


## Deprecated options

None