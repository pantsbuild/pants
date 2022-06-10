---
title: "paths"
slug: "reference-paths"
hidden: false
createdAt: "2022-06-02T21:09:25.021Z"
updatedAt: "2022-06-02T21:09:25.412Z"
---
```
./pants paths [args]
```
List the paths between two addresses.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[paths]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--paths-output-file=&lt;path&gt;</code><br>
  <code>PANTS_PATHS_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>from</code></h3>
  <code>--paths-from=&lt;str&gt;</code><br>
  <code>PANTS_PATHS_FROM</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The path starting address
</div>
<br>

<div style="color: purple">
  <h3><code>to</code></h3>
  <code>--paths-to=&lt;str&gt;</code><br>
  <code>PANTS_PATHS_TO</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The path end address
</div>
<br>


## Advanced options

None

## Deprecated options

None