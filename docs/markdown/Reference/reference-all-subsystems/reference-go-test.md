---
title: "go-test"
slug: "reference-go-test"
hidden: false
createdAt: "2022-06-02T21:09:42.772Z"
updatedAt: "2022-06-02T21:09:43.220Z"
---
Options for Go tests.

Backend: <span style="color: purple"><code>pants.backend.experimental.go</code></span>
Config section: <span style="color: purple"><code>[go-test]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--go-test-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_GO_TEST_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Go test binary, e.g. `--go-test-args='-run TestFoo -v'`.

Known Go test options will be transformed into the form expected by the test binary, e.g. `-v` becomes `-test.v`. Run `go help testflag` from the Go SDK to learn more about the options supported by Go test binaries.
</div>
<br>


## Advanced options

None

## Deprecated options

None