---
title: "python-thrift"
slug: "reference-python-thrift"
hidden: false
createdAt: "2022-06-02T21:10:05.285Z"
updatedAt: "2022-06-02T21:10:05.754Z"
---
Options specific to generating Python from Thrift using Apache Thrift

Backend: <span style="color: purple"><code>pants.backend.codegen.thrift.apache.python</code></span>
Config section: <span style="color: purple"><code>[python-thrift]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>options</code></h3>
  <code>--python-thrift-options=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_THRIFT_OPTIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Code generation options specific to the Python code generator to pass to the Apache `thift` binary via the `-gen py` argument. See `thrift -help` for supported values.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>infer_runtime_dependency</code></h3>
  <code>--[no-]python-thrift-infer-runtime-dependency</code><br>
  <code>PANTS_PYTHON_THRIFT_INFER_RUNTIME_DEPENDENCY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If True, will add a dependency on a `python_requirement` target exposing the `thrift` module (usually from the `thrift` requirement).

If `[python].enable_resolves` is set, Pants will only infer dependencies on `python_requirement` targets that use the same resolve as the particular `thrift_source` / `thrift_source` target uses, which is set via its `python_resolve` field.

Unless this option is disabled, Pants will error if no relevant target is found or more than one is found which causes ambiguity.
</div>
<br>


## Deprecated options

None