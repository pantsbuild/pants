---
title: "google-java-format"
slug: "reference-google-java-format"
hidden: false
createdAt: "2022-06-02T21:09:44.946Z"
updatedAt: "2022-06-02T21:09:45.466Z"
---
Google Java Format (https://github.com/google/google-java-format)

Backend: <span style="color: purple"><code>pants.backend.experimental.java.lint.google_java_format</code></span>
Config section: <span style="color: purple"><code>[google-java-format]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]google-java-format-skip</code><br>
  <code>PANTS_GOOGLE_JAVA_FORMAT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Google Java Format when running `./pants fmt` and `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>aosp</code></h3>
  <code>--[no-]google-java-format-aosp</code><br>
  <code>PANTS_GOOGLE_JAVA_FORMAT_AOSP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Use AOSP style instead of Google Style (4-space indentation). ("AOSP" is the Android Open Source Project.)
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--google-java-format-version=&lt;str&gt;</code><br>
  <code>PANTS_GOOGLE_JAVA_FORMAT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1.13.0</code></span>

<br>

Version string for the tool. This is available for substitution in the `[google-java-format].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--google-java-format-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_GOOGLE_JAVA_FORMAT_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "com.google.googlejavaformat:google-java-format:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[google-java-format].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--google-java-format-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_GOOGLE_JAVA_FORMAT_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/java/lint/google_java_format/google_java_format.default.lockfile.txt for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=google-java-format`.
</div>
<br>


## Deprecated options

None