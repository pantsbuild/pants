---
title: "apache-thrift"
slug: "reference-apache-thrift"
hidden: false
createdAt: "2022-06-02T21:09:32.844Z"
updatedAt: "2022-06-02T21:09:33.206Z"
---
Apache Thrift IDL compiler (https://thrift.apache.org/).

Backend: <span style="color: purple"><code>pants.backend.codegen.thrift.apache.python</code></span>
Config section: <span style="color: purple"><code>[apache-thrift]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>thrift_search_paths</code></h3>
  <code>--apache-thrift-thrift-search-paths=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_APACHE_THRIFT_THRIFT_SEARCH_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;PATH&gt;"
]</pre></span>

<br>

A list of paths to search for Thrift.

Specify absolute paths to directories with the `thrift` binary, e.g. `/usr/bin`. Earlier entries will be searched first.

The special string `"<PATH>"` will expand to the contents of the PATH env var.
</div>
<br>

<div style="color: purple">
  <h3><code>expected_version</code></h3>
  <code>--apache-thrift-expected-version=&lt;str&gt;</code><br>
  <code>PANTS_APACHE_THRIFT_EXPECTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0.15</code></span>

<br>

The major/minor version of Apache Thrift that you are using, such as `0.15`.

Pants will only use Thrift binaries from `--thrift-search-paths` that have the expected version, and it will error if none are found.

Do not include the patch version.
</div>
<br>


## Advanced options

None

## Deprecated options

None