---
title: "pyoxidizer"
slug: "reference-pyoxidizer"
hidden: false
createdAt: "2022-06-02T21:10:00.053Z"
updatedAt: "2022-06-02T21:10:00.559Z"
---
The PyOxidizer utility for packaging Python code in a Rust binary (https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer.html).

Used with the `pyoxidizer_binary` target.

Backend: <span style="color: purple"><code>pants.backend.experimental.python.packaging.pyoxidizer</code></span>
Config section: <span style="color: purple"><code>[pyoxidizer]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--pyoxidizer-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_PYOXIDIZER_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to PyOxidizer, e.g. `--pyoxidizer-args='--release'`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--pyoxidizer-version=&lt;str&gt;</code><br>
  <code>PANTS_PYOXIDIZER_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>pyoxidizer==0.18.0</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--pyoxidizer-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYOXIDIZER_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>interpreter_constraints</code></h3>
  <code>--pyoxidizer-interpreter-constraints=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYOXIDIZER_INTERPRETER_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "CPython&gt;=3.8,&lt;4"
]</pre></span>

<br>

Python interpreter constraints for this tool.
</div>
<br>

<div style="color: purple">
  <h3><code>console_script</code></h3>
  <code>--pyoxidizer-console-script=&lt;str&gt;</code><br>
  <code>PANTS_PYOXIDIZER_CONSOLE_SCRIPT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>pyoxidizer</code></span>

<br>

The console script for the tool. Using this option is generally preferable to (and mutually exclusive with) specifying an --entry-point since console script names have a higher expectation of staying stable across releases of the tool. Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>entry_point</code></h3>
  <code>--pyoxidizer-entry-point=&lt;str&gt;</code><br>
  <code>PANTS_PYOXIDIZER_ENTRY_POINT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The entry point for the tool. Generally you only want to use this option if the tool does not offer a --console-script (which this option is mutually exclusive with). Usually, you will not want to change this from the default.
</div>
<br>


## Deprecated options

None