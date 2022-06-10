---
title: "check"
slug: "reference-check"
hidden: false
createdAt: "2022-06-02T21:09:13.307Z"
updatedAt: "2022-06-02T21:09:13.627Z"
---
```
./pants check [args]
```
Run type checking or the lightest variant of compilation available for a language.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[check]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>only</code></h3>
  <code>--check-only=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_CHECK_ONLY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Only run these checkerss and skip all others.

The checkers names are outputted at the final summary of running this goal, e.g. `mypy` and `javac`. You can also run `check --only=fake` to get a list of all activated checkerss.

You can repeat this option, e.g. `check --only=mypy --only=javac` or `check --only=['mypy', 'javac']`.
</div>
<br>


## Advanced options

None

## Deprecated options

None