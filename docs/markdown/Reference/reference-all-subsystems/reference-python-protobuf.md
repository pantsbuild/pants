---
title: "python-protobuf"
slug: "reference-python-protobuf"
hidden: false
createdAt: "2022-06-02T21:10:04.020Z"
updatedAt: "2022-06-02T21:10:04.426Z"
---
Options related to the Protobuf Python backend.

See [Protobuf and gRPC](doc:protobuf-python).

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.python</code></span>
Config section: <span style="color: purple"><code>[python-protobuf]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>mypy_plugin</code></h3>
  <code>--[no-]python-protobuf-mypy-plugin</code><br>
  <code>PANTS_PYTHON_PROTOBUF_MYPY_PLUGIN</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Use the `mypy-protobuf` plugin (https://github.com/dropbox/mypy-protobuf) to also generate .pyi type stubs.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>infer_runtime_dependency</code></h3>
  <code>--[no-]python-protobuf-infer-runtime-dependency</code><br>
  <code>PANTS_PYTHON_PROTOBUF_INFER_RUNTIME_DEPENDENCY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If True, will add a dependency on a `python_requirement` target exposing the `protobuf` module (usually from the `protobuf` requirement). If the `protobuf_source` target sets `grpc=True`, will also add a dependency on the `python_requirement` target exposing the `grpcio` module.

If `[python].enable_resolves` is set, Pants will only infer dependencies on `python_requirement` targets that use the same resolve as the particular `protobuf_source` / `protobuf_sources` target uses, which is set via its `python_resolve` field.

Unless this option is disabled, Pants will error if no relevant target is found or if more than one is found which causes ambiguity.
</div>
<br>


## Deprecated options

None