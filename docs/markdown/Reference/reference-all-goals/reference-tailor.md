---
title: "tailor"
slug: "reference-tailor"
hidden: false
createdAt: "2022-06-02T21:09:29.424Z"
updatedAt: "2022-06-02T21:09:29.850Z"
---
```
./pants tailor [args]
```
Auto-generate BUILD file targets for new source files.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[tailor]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>check</code></h3>
  <code>--[no-]tailor-check</code><br>
  <code>PANTS_TAILOR_CHECK</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Do not write changes to disk, only write back what would change. Return code 0 means there would be no changes, and 1 means that there would be.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>build_file_name</code></h3>
  <code>--tailor-build-file-name=&lt;str&gt;</code><br>
  <code>PANTS_TAILOR_BUILD_FILE_NAME</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>BUILD</code></span>

<br>

The name to use for generated BUILD files.

This must be compatible with `[GLOBAL].build_patterns`.
</div>
<br>

<div style="color: purple">
  <h3><code>build_file_header</code></h3>
  <code>--tailor-build-file-header=&lt;str&gt;</code><br>
  <code>PANTS_TAILOR_BUILD_FILE_HEADER</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

A header, e.g., a copyright notice, to add to the content of created BUILD files.
</div>
<br>

<div style="color: purple">
  <h3><code>build_file_indent</code></h3>
  <code>--tailor-build-file-indent=&lt;str&gt;</code><br>
  <code>PANTS_TAILOR_BUILD_FILE_INDENT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>    </code></span>

<br>

The indent to use when auto-editing BUILD files.
</div>
<br>

<div style="color: purple">
  <h3><code>alias_mapping</code></h3>
  <code>--tailor-alias-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_TAILOR_ALIAS_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A mapping from standard target type to custom type to use instead. The custom type can be a custom target type or a macro that offers compatible functionality to the one it replaces (see [Macros](doc:macros)).
</div>
<br>

<div style="color: purple">
  <h3><code>ignore_paths</code></h3>
  <code>--tailor-ignore-paths=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_TAILOR_IGNORE_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Do not edit or create BUILD files at these paths.

Can use literal file names and/or globs, e.g. `['project/BUILD, 'ignore_me/**']`.

This augments the option `[GLOBAL].build_ignore`, which tells Pants to also not _read_ BUILD files at certain paths. In contrast, this option only tells Pants to not edit/create BUILD files at the specified paths.
</div>
<br>

<div style="color: purple">
  <h3><code>ignore_adding_targets</code></h3>
  <code>--tailor-ignore-adding-targets=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_TAILOR_IGNORE_ADDING_TARGETS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Do not add these target definitions.

Expects a list of target addresses that would normally be added by `tailor`, e.g. `['project:tgt']`. To find these names, you can run `tailor --check`, then combine the BUILD file path with the target's name. For example, if `tailor` would add the target `bin` to `project/BUILD`, then the address would be `project:bin`. If the BUILD file is at the root of your repository, use `//` for the path, e.g. `//:bin`.

Does not work with macros.
</div>
<br>


## Deprecated options

None