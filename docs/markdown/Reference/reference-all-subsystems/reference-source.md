---
title: "source"
slug: "reference-source"
hidden: false
createdAt: "2022-06-02T21:10:15.917Z"
updatedAt: "2022-06-02T21:10:16.276Z"
---
Configuration for roots of source trees.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[source]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>root_patterns</code></h3>
  <code>--source-root-patterns=&quot;[[&quot;pattern1&quot;, &quot;pattern2&quot;, ...], [&quot;pattern1&quot;, &quot;pattern2&quot;, ...], ...]&quot;</code><br>
  <code>PANTS_SOURCE_ROOT_PATTERNS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "/",
  "src",
  "src/python",
  "src/py",
  "src/thrift",
  "src/protobuf",
  "src/protos",
  "src/scala",
  "src/java"
]</pre></span>

<br>

A list of source root suffixes. A directory with this suffix will be considered a potential source root. E.g., `src/python` will match `<buildroot>/src/python`, `<buildroot>/project1/src/python` etc. Prepend a `/` to anchor the match at the buildroot. E.g., `/src/python` will match `<buildroot>/src/python` but not `<buildroot>/project1/src/python`. A `*` wildcard will match a single path segment, e.g., `src/*` will match `<buildroot>/src/python` and `<buildroot>/src/rust`. Use `/` to signify that the buildroot itself is a source root. See [Source roots](doc:source-roots).
</div>
<br>

<div style="color: purple">
  <h3><code>marker_filenames</code></h3>
  <code>--source-marker-filenames=&quot;[filename, filename, ...]&quot;</code><br>
  <code>PANTS_SOURCE_MARKER_FILENAMES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

The presence of a file of this name in a directory indicates that the directory is a source root. The content of the file doesn't matter, and may be empty. Useful when you can't or don't wish to centrally enumerate source roots via `root_patterns`.
</div>
<br>


## Deprecated options

None