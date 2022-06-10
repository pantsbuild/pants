---
title: "setuptools"
slug: "reference-setuptools"
hidden: false
createdAt: "2022-06-02T21:10:13.015Z"
updatedAt: "2022-06-02T21:10:13.451Z"
---
Python setuptools, used to package `python_distribution` targets.

Backend: <span style="color: purple"><code>pants.backend.python</code></span>
Config section: <span style="color: purple"><code>[setuptools]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--setuptools-version=&lt;str&gt;</code><br>
  <code>PANTS_SETUPTOOLS_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>setuptools&gt;=50.3.0,&lt;58.0</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--setuptools-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SETUPTOOLS_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "wheel&gt;=0.35.1,&lt;0.38"
]</pre></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--setuptools-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_SETUPTOOLS_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` and `--extra-requirements` options, and the tool's interpreter constraints are compatible with the default. Pants will error or warn if the lockfile is not compatible (controlled by `[python].invalid_lockfile_behavior`). See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/subsystems/setuptools.lock for the default lockfile contents.

Set to the string `<none>` to opt out of using a lockfile. We do not recommend this, though, as lockfiles are essential for reproducible builds.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants generate-lockfiles --resolve=setuptools`.

As explained at [Third-party dependencies](doc:python-third-party-dependencies), lockfile generation via `generate-lockfiles` does not always work and you may want to manually generate the lockfile. You will want to set `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about missing lockfile headers.
</div>
<br>


## Deprecated options

None