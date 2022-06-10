---
title: "experimental_shell_command"
slug: "reference-experimental_shell_command"
hidden: false
createdAt: "2022-06-02T21:10:25.152Z"
updatedAt: "2022-06-02T21:10:25.641Z"
---
Execute any external tool for its side effects.

Example BUILD file:

    experimental_shell_command(
        command="./my-script.sh --flag",
        tools=["tar", "curl", "cat", "bash", "env"],
        dependencies=[":scripts"],
        outputs=["results/", "logs/my-script.log"],
    )

    shell_sources(name="scripts")

Remember to add this target to the dependencies of each consumer, such as your `python_tests` or `docker_image`. When relevant, Pants will run your `command` and insert the `outputs` into that consumer's context.

The command may be retried and/or cancelled, so ensure that it is idempotent.

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

## <code>log_output</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

Set to true if you want the output from the command logged to the console.

## <code>outputs</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Specify the shell command output files and directories.

Use a trailing slash on directory names, i.e. `my_dir/`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>timeout</code>

<span style="color: purple">type: <code>int | None</code></span>
<span style="color: green">default: <code>30</code></span>

Command execution timeout (in seconds).

## <code>tools</code>

<span style="color: purple">type: <code>Iterable[str]</code></span>
<span style="color: green">required</span>

Specify required executable tools that might be used.

Only the tools explicitly provided will be available on the search PATH, and these tools must be found on the paths provided by [shell-setup].executable_search_paths (which defaults to the system PATH).