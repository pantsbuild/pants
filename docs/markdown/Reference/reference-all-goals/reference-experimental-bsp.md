---
title: "experimental-bsp"
slug: "reference-experimental-bsp"
hidden: false
createdAt: "2022-06-02T21:09:15.879Z"
updatedAt: "2022-06-02T21:09:16.318Z"
---
```
./pants experimental-bsp [args]
```
Setup repository for Build Server Protocol (https://build-server-protocol.github.io/).

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[experimental-bsp]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>groups_config_files</code></h3>
  <code>--experimental-bsp-groups-config-files=&quot;[&lt;file_option&gt;, &lt;file_option&gt;, ...]&quot;</code><br>
  <code>PANTS_EXPERIMENTAL_BSP_GROUPS_CONFIG_FILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

A list of config files that define groups of Pants targets to expose to IDEs via Build Server Protocol.

Pants generally uses fine-grained targets to define the components of a build (in many cases on a file-by-file basis). Many IDEs, however, favor coarse-grained targets that contain large numbers of source files. To accommodate this distinction, the Pants BSP server will compute a set of BSP build targets to use from the groups specified in the config files set for this option. Each group will become one or more BSP build targets.

Each config file is a TOML file with a `groups` dictionary with the following format for an entry:

    # The dictionary key is used to identify the group. It must be unique.
    [groups.ID1]:
    # One or more Pants address specs defining what targets to include in the group.
    addresses = [
      "src/jvm::",
      "tests/jvm::",
    ]
    # Filter targets to a specific resolve. Targets in a group must be from a single resolve.
    # Format of filter is `TYPE:RESOLVE_NAME`. The only supported TYPE is `jvm`. RESOLVE_NAME must be
    # a valid resolve name.
    resolve = "jvm:jvm-default"
    display_name = "Display Name" # (Optional) Name shown to the user in the IDE.
    base_directory = "path/from/build/root" # (Optional) Hint to the IDE for where the build target should "live."

Pants will merge the contents of the config files together. If the same ID is used for a group definition, in multiple config files, the definition in the latter config file will take effect.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>server</code></h3>
  <code>--[no-]experimental-bsp-server</code><br>
  <code>PANTS_EXPERIMENTAL_BSP_SERVER</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Run the Build Server Protocol server. Pants will receive BSP RPC requests via the console. This should only ever be invoked via the IDE.
</div>
<br>

<div style="color: purple">
  <h3><code>runner_env_vars</code></h3>
  <code>--experimental-bsp-runner-env-vars=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_EXPERIMENTAL_BSP_RUNNER_ENV_VARS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "PATH"
]</pre></span>

<br>

Environment variables to set in the BSP runner script when setting up BSP in a repository. Entries are either strings in the form `ENV_VAR=value` to set an explicit value; or just `ENV_VAR` to copy the value from Pants' own environment when the experimental-bsp goal was run.

This option only takes effect when the BSP runner script is written. If the option changes, you must run `./pants experimental-bsp` again to write a new copy of the BSP runner script.

Note: The environment variables passed to the Pants BSP server will be those set for your IDE and not your shell. For example, on macOS, the IDE is generally launched by `launchd` after clicking on a Dock icon, and not from the shell. Thus, any environment variables set for your shell will likely not be seen by the Pants BSP server. At the very least, on macOS consider writing an explicit PATH into the BSP runner script via this option.
</div>
<br>


## Deprecated options

None