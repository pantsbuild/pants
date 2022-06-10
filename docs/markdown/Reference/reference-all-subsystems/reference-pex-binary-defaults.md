---
title: "pex-binary-defaults"
slug: "reference-pex-binary-defaults"
hidden: false
createdAt: "2022-06-02T21:09:56.729Z"
updatedAt: "2022-06-02T21:09:57.125Z"
---
Default settings for creating PEX executables.

Backend: <span style="color: purple"><code>pants.backend.python</code></span>
Config section: <span style="color: purple"><code>[pex-binary-defaults]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>emit_warnings</code></h3>
  <code>--[no-]pex-binary-defaults-emit-warnings</code><br>
  <code>PANTS_PEX_BINARY_DEFAULTS_EMIT_WARNINGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Whether built PEX binaries should emit PEX warnings at runtime by default.

Can be overridden by specifying the `emit_warnings` parameter of individual `pex_binary` targets
</div>
<br>

<div style="color: purple">
  <h3><code>resolve_local_platforms</code></h3>
  <code>--[no-]pex-binary-defaults-resolve-local-platforms</code><br>
  <code>PANTS_PEX_BINARY_DEFAULTS_RESOLVE_LOCAL_PLATFORMS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

For each of the `platforms` specified for a `pex_binary` target, attempt to find a local interpreter that matches.

If a matching interpreter is found, use the interpreter to resolve distributions and build any that are only available in source distribution form. If no matching interpreter is found (or if this option is `False`), resolve for the platform by accepting only pre-built binary distributions (wheels).
</div>
<br>


## Deprecated options

None