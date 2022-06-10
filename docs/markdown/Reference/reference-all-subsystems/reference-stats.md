---
title: "stats"
slug: "reference-stats"
hidden: false
createdAt: "2022-06-02T21:10:16.600Z"
updatedAt: "2022-06-02T21:10:17.034Z"
---
An aggregator for Pants stats, such as cache metrics.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[stats]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>log</code></h3>
  <code>--[no-]stats-log</code><br>
  <code>PANTS_STATS_LOG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

At the end of the Pants run, log all counter metrics and summaries of observation histograms, e.g. the number of cache hits and the time saved by caching.

For histogram summaries to work, you must add `hdrhistogram` to `[GLOBAL].plugins`.
</div>
<br>

<div style="color: purple">
  <h3><code>memory_summary</code></h3>
  <code>--[no-]stats-memory-summary</code><br>
  <code>PANTS_STATS_MEMORY_SUMMARY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

At the end of the Pants run, report a summary of memory usage.

Keys are the total size in bytes, the count, and the name. Note that the total size is for all instances added together, so you can use total_size // count to get the average size.
</div>
<br>


## Deprecated options

None