---
title: "list"
slug: "reference-list"
hidden: false
createdAt: "2022-06-02T21:09:23.217Z"
updatedAt: "2022-06-02T21:09:23.620Z"
---
```
./pants list [args]
```
Lists all targets matching the file or target arguments.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[list]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--list-output-file=&lt;path&gt;</code><br>
  <code>PANTS_LIST_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>sep</code></h3>
  <code>--list-sep=&lt;separator&gt;</code><br>
  <code>PANTS_LIST_SEP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>\n</code></span>

<br>

String to use to separate lines in line-oriented output.
</div>
<br>

<div style="color: purple">
  <h3><code>documented</code></h3>
  <code>--[no-]list-documented</code><br>
  <code>PANTS_LIST_DOCUMENTED</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Print only targets that are documented with a description.
</div>
<br>


## Advanced options

None

## Deprecated options

None