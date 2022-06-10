---
title: "python-repos"
slug: "reference-python-repos"
hidden: false
createdAt: "2022-06-02T21:10:04.623Z"
updatedAt: "2022-06-02T21:10:05.051Z"
---
External Python code repositories, such as PyPI.

These options may be used to point to custom cheeseshops when resolving requirements.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[python-repos]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>repos</code></h3>
  <code>--python-repos-repos=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_REPOS_REPOS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

URLs of code repositories to look for requirements. In Pip and Pex, this option corresponds to the `--find-links` option.
</div>
<br>

<div style="color: purple">
  <h3><code>indexes</code></h3>
  <code>--python-repos-indexes=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_REPOS_INDEXES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "https://pypi.org/simple/"
]</pre></span>

<br>

URLs of code repository indexes to look for requirements. If set to an empty list, then Pex will use no indices (meaning it will not use PyPI). The values should be compliant with PEP 503.
</div>
<br>


## Deprecated options

None