---
title: "shell-setup"
slug: "reference-shell-setup"
hidden: false
createdAt: "2022-06-02T21:10:13.678Z"
updatedAt: "2022-06-02T21:10:14.352Z"
---
Options for Pants's Shell support.

Backend: <span style="color: purple"><code>pants.backend.shell</code></span>
Config section: <span style="color: purple"><code>[shell-setup]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>executable_search_paths</code></h3>
  <code>--shell-setup-executable-search-paths=&quot;[&lt;binary-paths&gt;, &lt;binary-paths&gt;, ...]&quot;</code><br>
  <code>PANTS_SHELL_SETUP_EXECUTABLE_SEARCH_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;PATH&gt;"
]</pre></span>

<br>

The PATH value that will be used to find shells and to run certain processes like the shunit2 test runner.

The special string `"<PATH>"` will expand to the contents of the PATH env var.
</div>
<br>

<div style="color: purple">
  <h3><code>dependency_inference</code></h3>
  <code>--[no-]shell-setup-dependency-inference</code><br>
  <code>PANTS_SHELL_SETUP_DEPENDENCY_INFERENCE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer Shell dependencies on other Shell files by analyzing `source` statements.
</div>
<br>


## Deprecated options

None