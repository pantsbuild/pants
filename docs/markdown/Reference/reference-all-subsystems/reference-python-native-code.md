---
title: "python-native-code"
slug: "reference-python-native-code"
hidden: false
createdAt: "2022-06-02T21:10:03.383Z"
updatedAt: "2022-06-02T21:10:03.813Z"
---
Options for building native code using Python, e.g. when resolving distributions.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[python-native-code]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>cpp_flags</code></h3>
  <code>--python-native-code-cpp-flags=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_NATIVE_CODE_CPP_FLAGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Override the `CPPFLAGS` environment variable for any forked subprocesses.
</div>
<br>

<div style="color: purple">
  <h3><code>ld_flags</code></h3>
  <code>--python-native-code-ld-flags=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_NATIVE_CODE_LD_FLAGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Override the `LDFLAGS` environment variable for any forked subprocesses.
</div>
<br>


## Deprecated options

None