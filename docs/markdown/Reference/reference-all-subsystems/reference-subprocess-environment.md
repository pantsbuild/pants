---
title: "subprocess-environment"
slug: "reference-subprocess-environment"
hidden: false
createdAt: "2022-06-02T21:10:17.234Z"
updatedAt: "2022-06-02T21:10:17.752Z"
---
Environment settings for forked subprocesses.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[subprocess-environment]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>env_vars</code></h3>
  <code>--subprocess-environment-env-vars=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SUBPROCESS_ENVIRONMENT_ENV_VARS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "LANG",
  "LC&lowbar;CTYPE",
  "LC&lowbar;ALL",
  "SSL&lowbar;CERT&lowbar;FILE",
  "SSL&lowbar;CERT&lowbar;DIR"
]</pre></span>

<br>

Environment variables to set for process invocations.

Entries are either strings in the form `ENV_VAR=value` to set an explicit value; or just `ENV_VAR` to copy the value from Pants's own environment.

See [Options](doc:options)#addremove-semantics for how to add and remove Pants's default for this option.
</div>
<br>


## Deprecated options

None