---
title: "scalapb"
slug: "reference-scalapb"
hidden: false
createdAt: "2022-06-02T21:10:10.282Z"
updatedAt: "2022-06-02T21:10:10.666Z"
---
The ScalaPB protocol buffer compiler (https://scalapb.github.io/).

Backend: <span style="color: purple"><code>pants.backend.experimental.codegen.protobuf.scala</code></span>
Config section: <span style="color: purple"><code>[scalapb]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>jvm_plugins</code></h3>
  <code>--scalapb-jvm-plugins=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SCALAPB_JVM_PLUGINS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

A list of JVM-based `protoc` plugins to invoke when generating Scala code from protobuf files. The format for each plugin specifier is `NAME=ARTIFACT` where NAME is the name of the plugin and ARTIFACT is either the address of a `jvm_artifact` target or the colon-separated Maven coordinate for the plugin's jar artifact.

For example, to invoke the fs2-grpc protoc plugin, the following option would work: `--scalapb-jvm-plugins=fs2=org.typelevel:fs2-grpc-codegen_2.12:2.3.1`. (Note: you would also need to set --scalapb-runtime-dependencies appropriately to include the applicable runtime libraries for your chosen protoc plugins.)
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--scalapb-version=&lt;str&gt;</code><br>
  <code>PANTS_SCALAPB_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0.11.6</code></span>

<br>

Version string for the tool. This is available for substitution in the `[scalapb].artifacts` option by including the string `{version}`.
</div>
<br>

<div style="color: purple">
  <h3><code>artifacts</code></h3>
  <code>--scalapb-artifacts=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SCALAPB_ARTIFACTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "com.thesamet.scalapb:scalapbc&lowbar;2.13:{version}"
]</pre></span>

<br>

Artifact requirements for this tool using specified as either the address of a `jvm_artifact` target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). For Maven coordinates, the string `{version}` version will be substituted with the value of the `[scalapb].version` option.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--scalapb-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_SCALAPB_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` option. See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/codegen/protobuf/scala/scalapbc.default.lockfile.txt for the default lockfile contents.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants jvm-generate-lockfiles --resolve=scalapb`.
</div>
<br>


## Deprecated options

None