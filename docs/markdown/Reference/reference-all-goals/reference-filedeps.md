---
title: "filedeps"
slug: "reference-filedeps"
hidden: false
createdAt: "2022-06-02T21:09:17.838Z"
updatedAt: "2022-06-02T21:09:18.226Z"
---
```
./pants filedeps [args]
```
List all source and BUILD files a target depends on.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[filedeps]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--filedeps-output-file=&lt;path&gt;</code><br>
  <code>PANTS_FILEDEPS_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>sep</code></h3>
  <code>--filedeps-sep=&lt;separator&gt;</code><br>
  <code>PANTS_FILEDEPS_SEP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>\n</code></span>

<br>

String to use to separate lines in line-oriented output.
</div>
<br>

<div style="color: purple">
  <h3><code>absolute</code></h3>
  <code>--[no-]filedeps-absolute</code><br>
  <code>PANTS_FILEDEPS_ABSOLUTE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

If True, output with absolute path. If unspecified, output with path relative to the build root.
</div>
<br>

<div style="color: purple">
  <h3><code>globs</code></h3>
  <code>--[no-]filedeps-globs</code><br>
  <code>PANTS_FILEDEPS_GLOBS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Instead of outputting filenames, output the original globs used in the BUILD file. This will not include exclude globs (i.e. globs that start with `!`).
</div>
<br>

<div style="color: purple">
  <h3><code>transitive</code></h3>
  <code>--[no-]filedeps-transitive</code><br>
  <code>PANTS_FILEDEPS_TRANSITIVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

If True, list files from all dependencies, including transitive dependencies. If unspecified, only list files from the target.
</div>
<br>


## Advanced options

None

## Deprecated options

None