---
title: "kotlin-infer"
slug: "reference-kotlin-infer"
hidden: false
createdAt: "2022-06-02T21:09:52.483Z"
updatedAt: "2022-06-02T21:09:52.940Z"
---
Options controlling which dependencies will be inferred for Kotlin targets.

Backend: <span style="color: purple"><code>pants.backend.experimental.kotlin</code></span>
Config section: <span style="color: purple"><code>[kotlin-infer]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>imports</code></h3>
  <code>--[no-]kotlin-infer-imports</code><br>
  <code>PANTS_KOTLIN_INFER_IMPORTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a target's dependencies by parsing import statements from sources.
</div>
<br>

<div style="color: purple">
  <h3><code>consumed_types</code></h3>
  <code>--[no-]kotlin-infer-consumed-types</code><br>
  <code>PANTS_KOTLIN_INFER_CONSUMED_TYPES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a target's dependencies by parsing consumed types from sources.
</div>
<br>


## Advanced options

None

## Deprecated options

None