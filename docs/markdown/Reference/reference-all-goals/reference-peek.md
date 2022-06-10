---
title: "peek"
slug: "reference-peek"
hidden: false
createdAt: "2022-06-02T21:09:25.613Z"
updatedAt: "2022-06-02T21:09:26.025Z"
---
```
./pants peek [args]
```
Display BUILD target info

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[peek]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--peek-output-file=&lt;path&gt;</code><br>
  <code>PANTS_PEEK_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>exclude_defaults</code></h3>
  <code>--[no-]peek-exclude-defaults</code><br>
  <code>PANTS_PEEK_EXCLUDE_DEFAULTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to leave off values that match the target-defined default values.
</div>
<br>


## Advanced options

None

## Deprecated options

None