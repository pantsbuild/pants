---
title: "yapf"
slug: "reference-yapf"
hidden: false
createdAt: "2022-06-02T21:10:21.504Z"
updatedAt: "2022-06-02T21:10:22.025Z"
---
A formatter for Python files (https://github.com/google/yapf).

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[yapf]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]yapf-skip</code><br>
  <code>PANTS_YAPF_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use yapf when running `./pants fmt` and `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--yapf-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_YAPF_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to yapf, e.g. `--yapf-args='--no-local-style'`.

Certain arguments, specifically `--recursive`, `--in-place`, and `--parallel`, will be ignored because Pants takes care of finding all the relevant files and running the formatting in parallel.
</div>
<br>

<div style="color: purple">
  <h3><code>export</code></h3>
  <code>--[no-]yapf-export</code><br>
  <code>PANTS_YAPF_EXPORT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, export a virtual environment with yapf when running `./pants export`.

This can be useful, for example, with IDE integrations to point your editor to the tool's binary.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--yapf-version=&lt;str&gt;</code><br>
  <code>PANTS_YAPF_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>yapf==0.32.0</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--yapf-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_YAPF_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "toml"
]</pre></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>interpreter_constraints</code></h3>
  <code>--yapf-interpreter-constraints=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_YAPF_INTERPRETER_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "CPython&gt;=3.7,&lt;4"
]</pre></span>

<br>

Python interpreter constraints for this tool.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--yapf-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_YAPF_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` and `--extra-requirements` options, and the tool's interpreter constraints are compatible with the default. Pants will error or warn if the lockfile is not compatible (controlled by `[python].invalid_lockfile_behavior`). See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/lint/yapf/yapf.lock for the default lockfile contents.

Set to the string `<none>` to opt out of using a lockfile. We do not recommend this, though, as lockfiles are essential for reproducible builds.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants generate-lockfiles --resolve=yapf`.

As explained at [Third-party dependencies](doc:python-third-party-dependencies), lockfile generation via `generate-lockfiles` does not always work and you may want to manually generate the lockfile. You will want to set `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about missing lockfile headers.
</div>
<br>

<div style="color: purple">
  <h3><code>console_script</code></h3>
  <code>--yapf-console-script=&lt;str&gt;</code><br>
  <code>PANTS_YAPF_CONSOLE_SCRIPT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>yapf</code></span>

<br>

The console script for the tool. Using this option is generally preferable to (and mutually exclusive with) specifying an --entry-point since console script names have a higher expectation of staying stable across releases of the tool. Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>entry_point</code></h3>
  <code>--yapf-entry-point=&lt;str&gt;</code><br>
  <code>PANTS_YAPF_ENTRY_POINT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The entry point for the tool. Generally you only want to use this option if the tool does not offer a --console-script (which this option is mutually exclusive with). Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>config</code></h3>
  <code>--yapf-config=&lt;file_option&gt;</code><br>
  <code>PANTS_YAPF_CONFIG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to style file understood by yapf (https://github.com/google/yapf#formatting-style/).

Setting this option will disable `[yapf].config_discovery`. Use this option if the config is located in a non-standard location.
</div>
<br>

<div style="color: purple">
  <h3><code>config_discovery</code></h3>
  <code>--[no-]yapf-config-discovery</code><br>
  <code>PANTS_YAPF_CONFIG_DISCOVERY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, Pants will include any relevant config files during runs (`.style.yapf`, `pyproject.toml`, and `setup.cfg`).

Use `[yapf].config` instead if your config is in a non-standard location.
</div>
<br>


## Deprecated options

None