---
title: "repl"
slug: "reference-repl"
hidden: false
createdAt: "2022-06-02T21:09:27.704Z"
updatedAt: "2022-06-02T21:09:28.079Z"
---
```
./pants repl [args]
```
Open a REPL with the specified code loadable.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[repl]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>shell</code></h3>
  <code>--repl-shell=&lt;str&gt;</code><br>
  <code>PANTS_REPL_SHELL</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Override the automatically-detected REPL program for the target(s) specified.
</div>
<br>

<div style="color: purple">
  <h3><code>restartable</code></h3>
  <code>--[no-]repl-restartable</code><br>
  <code>PANTS_REPL_RESTARTABLE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

True if the REPL should be restarted if its inputs have changed.
</div>
<br>


## Advanced options

None

## Deprecated options

None