---
title: "changed"
slug: "reference-changed"
hidden: false
createdAt: "2022-06-02T21:09:36.299Z"
updatedAt: "2022-06-02T21:09:36.694Z"
---
Tell Pants to detect what files and targets have changed from Git.

See [Advanced target selection](doc:advanced-target-selection).

Backend: <span style="color: purple"><code></code></span>
Config section: <span style="color: purple"><code>[changed]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>since</code></h3>
  <code>--changed-since=&lt;str&gt;</code><br>
  <code>PANTS_CHANGED_SINCE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Calculate changes since this Git spec (commit range/SHA/ref).
</div>
<br>

<div style="color: purple">
  <h3><code>diffspec</code></h3>
  <code>--changed-diffspec=&lt;str&gt;</code><br>
  <code>PANTS_CHANGED_DIFFSPEC</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Calculate changes contained within a given Git spec (commit range/SHA/ref).
</div>
<br>

<div style="color: purple">
  <h3><code>dependees</code></h3>
  <code>--changed-dependees=&lt;DependeesOption&gt;</code><br>
  <code>PANTS_CHANGED_DEPENDEES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>none, direct, transitive</code></span><br>
<span style="color: green">default: <code>none</code></span>

<br>

Include direct or transitive dependees of changed targets.
</div>
<br>


## Advanced options

None

## Deprecated options

None