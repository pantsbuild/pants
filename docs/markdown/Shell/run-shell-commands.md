---
title: "Run shell commands"
slug: "run-shell-commands"
excerpt: "How to execute arbitrary scripts and programs"
hidden: false
createdAt: "2021-10-04T12:37:58.934Z"
---
The [`shell_command`](doc:reference-shell_command) target allows you to run any command during a Pants execution, for the purpose of modifying or creating files to be used by other targets, or its (idempotent: see below) side-effects when accessing services over the network.

```python BUILD
shell_command(
    command="./my-script.sh download some-archive.tar.gz",
    tools=["curl", "env", "bash", "mkdir", "tar"],
    output_directories=["files"],
    dependencies=[":shell-scripts", ":images"]
)

shell_sources(name="shell-scripts")
files(name="images", sources=["*.png"])
```
```shell my-script.sh
#!/usr/bin/env bash
case "$1" in
    download)
        echo "Downloading $2..."
        curl https://my-storage.example.net/blob/$2 -O
        mkdir files && tar xzf $2 -C files ;;
     *)
        echo "Usage: $0 [download|...]" ;;
esac
```

The `shell_command` target
---------------------------------------

The `command` field is passed to `bash -c <command>`. The execution sandbox will include any files from the `dependencies` field. Any executable tools that might be used must be specified in the `tools` field, in order to be available on the `PATH` while executing the command.

The command is limited to operating on the specific set of input files provided as dependencies, and only produces output files for other targets to consume. It is not possible to mutate any file in the workspace.

In case there are resulting files that should be captured and passed to any consuming targets, list them in the `outputs` field. To capture directories, simply add the path to the directory, with a trailing slash (as in the example `”files/”`, above).

> 📘 Idempotency requirement
> 
> The shell command may be cancelled or retried any number of times, so it is important that any side effects are idempotent. That is, it should not matter if it is run several times, or only partially.


> 📘 Running other Pants targets as commands
>
> See the [`adhoc_tool`](doc:adhoc-tool) documentation for discussion of how to run source files, third-party tools, and version-matched system binaries from within the Pants sandbox.


The `run_shell_command` target
-------------------------------------------

Unlike `shell_command`, the [`run_shell_command` target](doc:reference-run_shell_command) runs directly in your workspace, without sandboxing.

This target type allows you to formalize the Pants dependencies of shell scripts, and track when their impact on your workspace might have changed. But since its outputs cannot be captured, it must be a root target in your build graph (i.e.: it may not be consumed by other targets).
