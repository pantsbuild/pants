---
title: "lint"
slug: "reference-lint"
hidden: false
createdAt: "2022-06-02T21:09:22.656Z"
updatedAt: "2022-06-02T21:09:23.012Z"
---
```
./pants lint [args]
```
Run all linters and/or formatters in check mode.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[lint]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>only</code></h3>
  <code>--lint-only=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_LINT_ONLY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Only run these linters and skip all others.

The linter names are outputted at the final summary of running this goal, e.g. `flake8` and `shellcheck`. You can also run `lint --only=fake` to get a list of all activated linters.

You can repeat this option, e.g. `lint --only=flake8 --only=shellcheck` or `lint --only=['flake8', 'shellcheck']`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>batch_size</code></h3>
  <code>--lint-batch-size=&lt;int&gt;</code><br>
  <code>PANTS_LINT_BATCH_SIZE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>128</code></span>

<br>

The target number of files to be included in each linter batch.

Linter processes are batched for a few reasons:

1. to avoid OS argument length limits (in processes which don't support argument files)
2. to support more stable cache keys than would be possible if all files were operated on in a single batch.
3. to allow for parallelism in linter processes which don't have internal parallelism, or -- if they do support internal parallelism -- to improve scheduling behavior when multiple processes are competing for cores and so internal parallelism cannot be used perfectly.

In order to improve cache hit rates (see 2.), batches are created at stable boundaries, and so this value is only a "target" batch size (rather than an exact value).
</div>
<br>


## Deprecated options

None