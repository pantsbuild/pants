---
title: "roots"
slug: "reference-roots"
hidden: false
createdAt: "2022-06-02T21:09:28.277Z"
updatedAt: "2022-06-02T21:09:28.613Z"
---
```
./pants roots [args]
```
List the repo's registered source roots.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[roots]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--roots-output-file=&lt;path&gt;</code><br>
  <code>PANTS_ROOTS_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>sep</code></h3>
  <code>--roots-sep=&lt;separator&gt;</code><br>
  <code>PANTS_ROOTS_SEP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>\n</code></span>

<br>

String to use to separate lines in line-oriented output.
</div>
<br>


## Advanced options

None

## Deprecated options

None


## Related subsystems
[source](reference-source)