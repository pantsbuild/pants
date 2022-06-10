---
title: "experimental_run_shell_command"
slug: "reference-experimental_run_shell_command"
hidden: false
createdAt: "2022-06-02T21:10:24.421Z"
updatedAt: "2022-06-02T21:10:24.905Z"
---
Run a script in the workspace, with all dependencies packaged/copied into a chroot.

Example BUILD file:

    experimental_run_shell_command(
        command="./scripts/my-script.sh --data-files-dir={chroot}",
        dependencies=["src/project/files:data"],
    )

The `command` may use either `{chroot}` on the command line, or the `$CHROOT` environment variable to get the root directory for where any dependencies are located.

In contrast to the `experimental_shell_command`, in addition to `workdir` you only have the `command` and `dependencies` fields as the `tools` you are going to use are already on the PATH which is inherited from the Pants environment. Also, the `outputs` does not apply, as any output files produced will end up directly in your project tree.

Backend: <span style="color: purple"><code>pants.backend.shell</code></span>

## <code>command</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

Shell command to execute.

The command is executed as 'bash -c <command>' by default.

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>workdir</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>&#x27;.&#x27;</code></span>

Sets the current working directory of the command, relative to the project root.