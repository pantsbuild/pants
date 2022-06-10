---
title: "cli"
slug: "reference-cli"
hidden: false
createdAt: "2022-06-02T21:09:36.896Z"
updatedAt: "2022-06-02T21:09:37.308Z"
---
Options for configuring CLI behavior, such as command line aliases.

Backend: <span style="color: purple"><code></code></span>
Config section: <span style="color: purple"><code>[cli]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>alias</code></h3>
  <code>--cli-alias=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_CLI_ALIAS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

Register command line aliases.

Example:

    [cli.alias]
    green = "fmt lint check"
    all-changed = "--changed-since=HEAD --changed-dependees=transitive"

This would allow you to run `./pants green all-changed`, which is shorthand for `./pants fmt lint check --changed-since=HEAD --changed-dependees=transitive`.

Notice: this option must be placed in a config file (e.g. `pants.toml` or `pantsrc`) to have any effect.
</div>
<br>


## Advanced options

None

## Deprecated options

None