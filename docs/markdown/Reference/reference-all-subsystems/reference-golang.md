---
title: "golang"
slug: "reference-golang"
hidden: false
createdAt: "2022-06-02T21:09:44.312Z"
updatedAt: "2022-06-02T21:09:44.664Z"
---
Options for Golang support.

Backend: <span style="color: purple"><code>pants.backend.experimental.go</code></span>
Config section: <span style="color: purple"><code>[golang]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>go_search_paths</code></h3>
  <code>--golang-go-search-paths=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_GOLANG_GO_SEARCH_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;PATH&gt;"
]</pre></span>

<br>

A list of paths to search for Go.

Specify absolute paths to directories with the `go` binary, e.g. `/usr/bin`. Earlier entries will be searched first.

The special string `"<PATH>"` will expand to the contents of the PATH env var.
</div>
<br>

<div style="color: purple">
  <h3><code>expected_version</code></h3>
  <code>--golang-expected-version=&lt;str&gt;</code><br>
  <code>PANTS_GOLANG_EXPECTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1.17</code></span>

<br>

The Go version you are using, such as `1.17`.

Pants will only use Go distributions from `--go-search-paths` that have the expected version, and it will error if none are found.

Do not include the patch version.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>subprocess_env_vars</code></h3>
  <code>--golang-subprocess-env-vars=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_GOLANG_SUBPROCESS_ENV_VARS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "LANG",
  "LC&lowbar;CTYPE",
  "LC&lowbar;ALL",
  "PATH"
]</pre></span>

<br>

Environment variables to set when invoking the `go` tool. Entries are either strings in the form `ENV_VAR=value` to set an explicit value; or just `ENV_VAR` to copy the value from Pants's own environment.
</div>
<br>


## Deprecated options

None