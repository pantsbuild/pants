---
title: "generate-lockfiles"
slug: "reference-generate-lockfiles"
hidden: false
createdAt: "2022-06-02T21:09:19.758Z"
updatedAt: "2022-06-02T21:09:20.092Z"
---
```
./pants generate-lockfiles [args]
```
Generate lockfiles for Python third-party dependencies.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[generate-lockfiles]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>resolve</code></h3>
  <code>--generate-lockfiles-resolve=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_GENERATE_LOCKFILES_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Only generate lockfiles for the specified resolve(s).

Resolves are the logical names for the different lockfiles used in your project. For your own code's dependencies, these come from the option `[python].resolves`. For tool lockfiles, resolve names are the options scope for that tool such as `black`, `pytest`, and `mypy-protobuf`.

For example, you can run `./pants generate-lockfiles --resolve=black --resolve=pytest --resolve=data-science` to only generate lockfiles for those two tools and your resolve named `data-science`.

If you specify an invalid resolve name, like 'fake', Pants will output all possible values.

If not specified, Pants will generate lockfiles for all resolves.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>custom_command</code></h3>
  <code>--generate-lockfiles-custom-command=&lt;str&gt;</code><br>
  <code>PANTS_GENERATE_LOCKFILES_CUSTOM_COMMAND</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

If set, lockfile headers will say to run this command to regenerate the lockfile, rather than running `./pants generate-lockfiles --resolve=<name>` like normal.
</div>
<br>


## Deprecated options

None