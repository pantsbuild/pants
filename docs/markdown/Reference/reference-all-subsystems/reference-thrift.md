---
title: "thrift"
slug: "reference-thrift"
hidden: false
createdAt: "2022-06-02T21:10:19.777Z"
updatedAt: "2022-06-02T21:10:20.290Z"
---
General Thrift IDL settings (https://thrift.apache.org/).

Backend: <span style="color: purple"><code>pants.backend.codegen.thrift.apache.python</code></span>
Config section: <span style="color: purple"><code>[thrift]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>dependency_inference</code></h3>
  <code>--[no-]thrift-dependency-inference</code><br>
  <code>PANTS_THRIFT_DEPENDENCY_INFERENCE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer Thrift dependencies on other Thrift files by analyzing import statements.
</div>
<br>


## Advanced options

None

## Deprecated options

None