---
title: "ktlint"
slug: "reference-ktlint"
hidden: false
createdAt: "2022-06-02T21:09:53.789Z"
updatedAt: "2022-06-02T21:09:54.137Z"
---
Ktlint, the anti-bikeshedding Kotlin linter with built-in formatter (https://ktlint.github.io/)

Backend: <span style="color: purple"><code>pants.backend.experimental.kotlin.lint.ktlint</code></span>
Config section: <span style="color: purple"><code>[ktlint]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]ktlint-skip</code><br>
  <code>PANTS_KTLINT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Ktlint when running `./pants fmt` and `./pants lint`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--ktlint-version=&lt;str&gt;</code><br>
  <code>PANTS_KTLINT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0.45.2</code></span>

<br>

Version string for the tool. This is available for substitution in the `[ktlint].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--ktlint-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_KTLINT_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "com.pinterest:ktlint:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[ktlint].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--ktlint-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_KTLINT_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/kotlin/lint/ktlint/ktlint.lock for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=ktlint`.
</div>
<br>


## Deprecated options

None