---
title: "dependees"
slug: "reference-dependees"
hidden: false
createdAt: "2022-06-02T21:09:14.476Z"
updatedAt: "2022-06-02T21:09:14.941Z"
---
```
./pants dependees [args]
```
List all targets that depend on any of the input files/targets.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[dependees]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--dependees-output-file=&lt;path&gt;</code><br>
  <code>PANTS_DEPENDEES_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>sep</code></h3>
  <code>--dependees-sep=&lt;separator&gt;</code><br>
  <code>PANTS_DEPENDEES_SEP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>\n</code></span>

<br>

String to use to separate lines in line-oriented output.
</div>
<br>

<div style="color: purple">
  <h3><code>transitive</code></h3>
  <code>--[no-]dependees-transitive</code><br>
  <code>PANTS_DEPENDEES_TRANSITIVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

List all transitive dependees. If unspecified, list direct dependees only.
</div>
<br>

<div style="color: purple">
  <h3><code>closed</code></h3>
  <code>--[no-]dependees-closed</code><br>
  <code>PANTS_DEPENDEES_CLOSED</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Include the input targets in the output, along with the dependees.
</div>
<br>


## Advanced options

None

## Deprecated options

None