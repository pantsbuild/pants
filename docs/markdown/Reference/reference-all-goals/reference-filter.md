---
title: "filter"
slug: "reference-filter"
hidden: false
createdAt: "2022-06-02T21:09:18.559Z"
updatedAt: "2022-06-02T21:09:18.895Z"
---
```
./pants filter [args]
```
Filter the input targets based on various criteria.

Most of the filtering options below are comma-separated lists of filtering criteria, with an implied logical OR between them, so that a target passes the filter if it matches any of the criteria in the list. A '-' prefix inverts the sense of the entire comma-separated list, so that a target passes the filter only if it matches none of the criteria in the list.

Each of the filtering options may be specified multiple times, with an implied logical AND between them.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[filter]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--filter-output-file=&lt;path&gt;</code><br>
  <code>PANTS_FILTER_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>sep</code></h3>
  <code>--filter-sep=&lt;separator&gt;</code><br>
  <code>PANTS_FILTER_SEP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>\n</code></span>

<br>

String to use to separate lines in line-oriented output.
</div>
<br>

<div style="color: purple">
  <h3><code>target_type</code></h3>
  <code>--filter-target-type=&quot;[[+-]type1,type2,..., [+-]type1,type2,..., ...]&quot;</code><br>
  <code>PANTS_FILTER_TARGET_TYPE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Filter on these target types, e.g. `resources` or `python_sources`.
</div>
<br>

<div style="color: purple">
  <h3><code>granularity</code></h3>
  <code>--filter-granularity=&lt;TargetGranularity&gt;</code><br>
  <code>PANTS_FILTER_GRANULARITY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>all, file, BUILD</code></span><br>
<span style="color: green">default: <code>all</code></span>

<br>

Filter to rendering only targets declared in BUILD files, only file-level targets, or all targets.
</div>
<br>

<div style="color: purple">
  <h3><code>address_regex</code></h3>
  <code>--filter-address-regex=&quot;[[+-]regex1,regex2,..., [+-]regex1,regex2,..., ...]&quot;</code><br>
  <code>PANTS_FILTER_ADDRESS_REGEX</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Filter on target addresses matching these regexes.
</div>
<br>

<div style="color: purple">
  <h3><code>tag_regex</code></h3>
  <code>--filter-tag-regex=&quot;[[+-]regex1,regex2,..., [+-]regex1,regex2,..., ...]&quot;</code><br>
  <code>PANTS_FILTER_TAG_REGEX</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Filter on targets with tags matching these regexes.
</div>
<br>


## Advanced options

None

## Deprecated options

None