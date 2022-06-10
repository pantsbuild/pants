---
title: "java-infer"
slug: "reference-java-infer"
hidden: false
createdAt: "2022-06-02T21:09:49.371Z"
updatedAt: "2022-06-02T21:09:49.754Z"
---
Options controlling which dependencies will be inferred for Java targets.

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>
Config section: <span style="color: purple"><code>[java-infer]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>imports</code></h3>
  <code>--[no-]java-infer-imports</code><br>
  <code>PANTS_JAVA_INFER_IMPORTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a target's dependencies by parsing import statements from sources.
</div>
<br>

<div style="color: purple">
  <h3><code>consumed_types</code></h3>
  <code>--[no-]java-infer-consumed-types</code><br>
  <code>PANTS_JAVA_INFER_CONSUMED_TYPES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a target's dependencies by parsing consumed types from sources.
</div>
<br>

<div style="color: purple">
  <h3><code>third_party_import_mapping</code></h3>
  <code>--java-infer-third-party-import-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_JAVA_INFER_THIRD_PARTY_IMPORT_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A dictionary mapping a Java package path to a JVM artifact coordinate (GROUP:ARTIFACT) without the version.

See `jvm_artifact` for more information on the mapping syntax.
</div>
<br>


## Advanced options

None

## Deprecated options

<div style="color: purple">
  <h3><code>third_party_imports</code></h3>
  <code>--[no-]java-infer-third-party-imports</code><br>
  <code>PANTS_JAVA_INFER_THIRD_PARTY_IMPORTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>
<p style="color: darkred">Deprecated, is scheduled to be removed in version: 2.13.0.dev0.<br>Controlled by the `--imports` flag.</p>
<br>

Infer a target's third-party dependencies using Java import statements.
</div>
<br>