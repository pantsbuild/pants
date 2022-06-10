---
title: "mypy-protobuf"
slug: "reference-mypy-protobuf"
hidden: false
createdAt: "2022-06-02T21:09:55.571Z"
updatedAt: "2022-06-02T21:09:55.903Z"
---
Configuration of the mypy-protobuf type stub generation plugin.

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.python</code></span>
Config section: <span style="color: purple"><code>[mypy-protobuf]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--mypy-protobuf-version=&lt;str&gt;</code><br>
  <code>PANTS_MYPY_PROTOBUF_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>mypy-protobuf==2.10</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--mypy-protobuf-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_MYPY_PROTOBUF_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>interpreter_constraints</code></h3>
  <code>--mypy-protobuf-interpreter-constraints=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_MYPY_PROTOBUF_INTERPRETER_CONSTRAINTS</code><br>
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
  <code>--mypy-protobuf-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_MYPY_PROTOBUF_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` and `--extra-requirements` options, and the tool's interpreter constraints are compatible with the default. Pants will error or warn if the lockfile is not compatible (controlled by `[python].invalid_lockfile_behavior`). See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/codegen/protobuf/python/mypy_protobuf.lock for the default lockfile contents.

Set to the string `<none>` to opt out of using a lockfile. We do not recommend this, though, as lockfiles are essential for reproducible builds.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants generate-lockfiles --resolve=mypy-protobuf`.

As explained at [Third-party dependencies](doc:python-third-party-dependencies), lockfile generation via `generate-lockfiles` does not always work and you may want to manually generate the lockfile. You will want to set `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about missing lockfile headers.
</div>
<br>


## Deprecated options

None