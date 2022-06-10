---
title: "pex"
slug: "reference-pex"
hidden: false
createdAt: "2022-06-02T21:09:56.119Z"
updatedAt: "2022-06-02T21:09:56.519Z"
---
How Pants uses Pex to run Python subprocesses.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[pex]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>executable_search_paths</code></h3>
  <code>--pex-executable-search-paths=&quot;[&lt;binary-paths&gt;, &lt;binary-paths&gt;, ...]&quot;</code><br>
  <code>PANTS_PEX_EXECUTABLE_SEARCH_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;PATH&gt;"
]</pre></span>

<br>

The PATH value that will be used by the PEX subprocess and any subprocesses it spawns.

The special string `"<PATH>"` will expand to the contents of the PATH env var.
</div>
<br>

<div style="color: purple">
  <h3><code>verbosity</code></h3>
  <code>--pex-verbosity=&lt;int&gt;</code><br>
  <code>PANTS_PEX_VERBOSITY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0</code></span>

<br>

Set the verbosity level of PEX logging, from 0 (no logging) up to 9 (max logging).
</div>
<br>

<div style="color: purple">
  <h3><code>venv_use_symlinks</code></h3>
  <code>--[no-]pex-venv-use-symlinks</code><br>
  <code>PANTS_PEX_VENV_USE_SYMLINKS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

When possible, use venvs whose site-packages directories are populated with symlinks.

Enabling this can save space in the `--named-caches-dir` directory and lead to slightly faster execution times for Pants Python goals. Some distributions do not work with symlinked venvs though, so you may not be able to enable this optimization as a result.
</div>
<br>


## Deprecated options

None