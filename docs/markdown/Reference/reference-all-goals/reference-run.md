---
title: "run"
slug: "reference-run"
hidden: false
createdAt: "2022-06-02T21:09:28.818Z"
updatedAt: "2022-06-02T21:09:29.206Z"
---
```
./pants run [args]
```
Runs a binary target.

This goal propagates the return code of the underlying executable.

If your application can safely be restarted while it is running, you can pass `restartable=True` on your binary target (for supported types), and the `run` goal will automatically restart them as all relevant files change. This can be particularly useful for server applications.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[run]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--run-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_RUN_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to the executed target, e.g. `--run-args='val1 val2 --debug'`.
</div>
<br>

<div style="color: purple">
  <h3><code>cleanup</code></h3>
  <code>--[no-]run-cleanup</code><br>
  <code>PANTS_RUN_CLEANUP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Whether to clean up the temporary directory in which the binary is chrooted. Set to false to retain the directory, e.g., for debugging.
</div>
<br>


## Advanced options

None

## Deprecated options

None