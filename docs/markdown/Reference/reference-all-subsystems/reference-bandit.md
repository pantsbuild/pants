---
title: "bandit"
slug: "reference-bandit"
hidden: false
createdAt: "2022-06-02T21:09:34.025Z"
updatedAt: "2022-06-02T21:09:34.427Z"
---
A tool for finding security issues in Python code (https://bandit.readthedocs.io).

Backend: <span style="color: purple"><code>pants.backend.python.lint.bandit</code></span>
Config section: <span style="color: purple"><code>[bandit]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]bandit-skip</code><br>
  <code>PANTS_BANDIT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Bandit when running `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--bandit-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_BANDIT_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Bandit, e.g. `--bandit-args='--skip B101,B308 --confidence'`.
</div>
<br>

<div style="color: purple">
  <h3><code>export</code></h3>
  <code>--[no-]bandit-export</code><br>
  <code>PANTS_BANDIT_EXPORT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, export a virtual environment with Bandit when running `./pants export`.

This can be useful, for example, with IDE integrations to point your editor to the tool's binary.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--bandit-version=&lt;str&gt;</code><br>
  <code>PANTS_BANDIT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>bandit&gt;=1.7.0,&lt;1.8</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--bandit-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BANDIT_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "setuptools",
  "GitPython==3.1.18"
]</pre></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--bandit-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_BANDIT_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` and `--extra-requirements` options, and the tool's interpreter constraints are compatible with the default. Pants will error or warn if the lockfile is not compatible (controlled by `[python].invalid_lockfile_behavior`). See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/lint/bandit/bandit.lock for the default lockfile contents.

Set to the string `<none>` to opt out of using a lockfile. We do not recommend this, though, as lockfiles are essential for reproducible builds.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants generate-lockfiles --resolve=bandit`.

As explained at [Third-party dependencies](doc:python-third-party-dependencies), lockfile generation via `generate-lockfiles` does not always work and you may want to manually generate the lockfile. You will want to set `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about missing lockfile headers.
</div>
<br>

<div style="color: purple">
  <h3><code>console_script</code></h3>
  <code>--bandit-console-script=&lt;str&gt;</code><br>
  <code>PANTS_BANDIT_CONSOLE_SCRIPT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>bandit</code></span>

<br>

The console script for the tool. Using this option is generally preferable to (and mutually exclusive with) specifying an --entry-point since console script names have a higher expectation of staying stable across releases of the tool. Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>entry_point</code></h3>
  <code>--bandit-entry-point=&lt;str&gt;</code><br>
  <code>PANTS_BANDIT_ENTRY_POINT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The entry point for the tool. Generally you only want to use this option if the tool does not offer a --console-script (which this option is mutually exclusive with). Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>config</code></h3>
  <code>--bandit-config=&lt;file_option&gt;</code><br>
  <code>PANTS_BANDIT_CONFIG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to a Bandit YAML config file (https://bandit.readthedocs.io/en/latest/config.html).
</div>
<br>


## Deprecated options

None