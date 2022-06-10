---
title: "scala"
slug: "reference-scala"
hidden: false
createdAt: "2022-06-02T21:10:07.509Z"
updatedAt: "2022-06-02T21:10:07.905Z"
---
Scala programming language

Backend: <span style="color: purple"><code>pants.backend.experimental.scala</code></span>
Config section: <span style="color: purple"><code>[scala]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>version_for_resolve</code></h3>
  <code>--scala-version-for-resolve=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_SCALA_VERSION_FOR_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A dictionary mapping the name of a resolve to the Scala version to use for all Scala targets consuming that resolve.

All Scala-compiled jars on a resolve's classpath must be "compatible" with one another and with all Scala-compiled first-party sources from `scala_sources` (and other Scala target types) using that resolve. The option sets the Scala version that will be used to compile all first-party sources using the resolve. This ensures that the compatibility property is maintained for a resolve. To support multiple Scala versions, use multiple resolves.
</div>
<br>


## Advanced options

None

## Deprecated options

None