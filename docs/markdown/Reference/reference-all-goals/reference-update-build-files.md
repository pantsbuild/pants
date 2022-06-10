---
title: "update-build-files"
slug: "reference-update-build-files"
hidden: false
createdAt: "2022-06-02T21:09:30.822Z"
updatedAt: "2022-06-02T21:09:31.228Z"
---
```
./pants update-build-files [args]
```
Format and fix safe deprecations in BUILD files.

This does not handle the full Pants upgrade. You must still manually change `pants_version` in `pants.toml` and you may need to manually address some deprecations. See [Upgrade tips](doc:upgrade-tips) for upgrade tips.

This goal is run without arguments. It will run over all BUILD files in your project.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[update-build-files]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>check</code></h3>
  <code>--[no-]update-build-files-check</code><br>
  <code>PANTS_UPDATE_BUILD_FILES_CHECK</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Do not write changes to disk, only write back what would change. Return code 0 means there would be no changes, and 1 means that there would be.
</div>
<br>

<div style="color: purple">
  <h3><code>fmt</code></h3>
  <code>--[no-]update-build-files-fmt</code><br>
  <code>PANTS_UPDATE_BUILD_FILES_FMT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Format BUILD files using Black or Yapf.

Set `[black].args` / `[yapf].args`, `[black].config` / `[yapf].config` , and `[black].config_discovery` / `[yapf].config_discovery` to change Black's or Yapf's behavior. Set `[black].interpreter_constraints` / `[yapf].interpreter_constraints` and `[python].interpreter_search_path` to change which interpreter is used to run the formatter.
</div>
<br>

<div style="color: purple">
  <h3><code>formatter</code></h3>
  <code>--update-build-files-formatter=&lt;Formatter&gt;</code><br>
  <code>PANTS_UPDATE_BUILD_FILES_FORMATTER</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>yapf, black</code></span><br>
<span style="color: green">default: <code>black</code></span>

<br>

Which formatter Pants should use to format BUILD files.
</div>
<br>

<div style="color: purple">
  <h3><code>fix_safe_deprecations</code></h3>
  <code>--[no-]update-build-files-fix-safe-deprecations</code><br>
  <code>PANTS_UPDATE_BUILD_FILES_FIX_SAFE_DEPRECATIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Automatically fix deprecations, such as target type renames, that are safe because they do not change semantics.
</div>
<br>


## Advanced options

None

## Deprecated options

<div style="color: purple">
  <h3><code>fix_python_macros</code></h3>
  <code>--[no-]update-build-files-fix-python-macros</code><br>
  <code>PANTS_UPDATE_BUILD_FILES_FIX_PYTHON_MACROS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>
<p style="color: darkred">Deprecated, is scheduled to be removed in version: 2.13.0.dev0.<br>No longer does anything as the old macros have been removed in favor of target generators.</p>
<br>

Deprecated.
</div>
<br>