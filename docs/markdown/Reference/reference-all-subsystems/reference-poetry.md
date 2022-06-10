---
title: "poetry"
slug: "reference-poetry"
hidden: false
createdAt: "2022-06-02T21:09:58.073Z"
updatedAt: "2022-06-02T21:09:58.481Z"
---
Used to generate lockfiles for third-party Python dependencies.

Backend: <span style="color: purple"><code>pants.backend.docker</code></span>
Config section: <span style="color: purple"><code>[poetry]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--poetry-version=&lt;str&gt;</code><br>
  <code>PANTS_POETRY_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>poetry==1.1.8</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--poetry-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_POETRY_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>interpreter_constraints</code></h3>
  <code>--poetry-interpreter-constraints=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_POETRY_INTERPRETER_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "CPython&gt;=3.7,&lt;4"
]</pre></span>

<br>

Python interpreter constraints for this tool.
</div>
<br>


## Deprecated options

None