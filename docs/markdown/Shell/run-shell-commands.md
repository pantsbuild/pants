---
title: "Run shell commands"
slug: "run-shell-commands"
excerpt: "How to execute arbitrary scripts and programs"
hidden: false
createdAt: "2021-10-04T12:37:58.934Z"
updatedAt: "2022-02-08T21:13:55.807Z"
---
The [`experimental_shell_command`](doc:reference-experimental_shell_command) target allows you to run any command during a Pants execution, for the purpose of modifying or creating files to be used by other targets, or its (idempotent: see below) side-effects when accessing services over the network.
[block:code]
{
  "codes": [
    {
      "code": "experimental_shell_command(\n    command=\"./my-script.sh download some-archive.tar.gz\",\n    tools=[\"curl\", \"env\", \"bash\", \"mkdir\", \"tar\"],\n    outputs=[\"files/\"],\n    dependencies=[\":shell-scripts\", \":images\"]\n)\n\nshell_sources(name=\"shell-scripts\")\nfiles(name=\"images\", sources=[\"*.png\"])",
      "language": "python",
      "name": "BUILD"
    },
    {
      "code": "#!/usr/bin/env bash\ncase \"$1\" in\n    download)\n        echo \"Downloading $2...\"\n        curl https://my-storage.example.net/blob/$2 -O\n        mkdir files && tar xzf $2 -C files ;;\n     *)\n        echo \"Usage: $0 [download|...]\" ;;\nesac",
      "language": "shell",
      "name": "my-script.sh"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "The `experimental_shell_command` target"
}
[/block]
The `command` field is passed to `bash -c <command>`. The execution sandbox will include any files from the `dependencies` field. Any executable tools that might be used must be specified in the `tools` field, in order to be available on the `PATH` while executing the command.

The command is limited to operating on the specific set of input files provided as dependencies, and only produces output files for other targets to consume. It is not possible to mutate any file in the workspace.

In case there are resulting files that should be captured and passed to any consuming targets, list them in the `outputs` field. To capture directories, simply add the path to the directory, with a trailing slash (as in the example `”files/”`, above).
[block:callout]
{
  "type": "info",
  "body": "The shell command may be cancelled or retried any number of times, so it is important that any side effects are idempotent. That is, it should not matter if it is run several times, or only partially.",
  "title": "Idempotency requirement"
}
[/block]

[block:callout]
{
  "type": "warning",
  "body": "We are gathering feedback on this target before we promote it from its experimental status. Please reach out to us on [Slack](doc:getting-help) or [GitHub](https://github.com/pantsbuild/pants) with your ideas or issues.",
  "title": "Feedback wanted"
}
[/block]

[block:api-header]
{
  "title": "The `experimental_run_shell_command` target"
}
[/block]
Unlike `experimental_shell_command`, the [`experimental_run_shell_command` target](doc:reference-experimental_run_shell_command) runs directly in your workspace, without sandboxing.

This target type allows you to formalize the Pants dependencies of shell scripts, and track when their impact on your workspace might have changed. But since its outputs cannot be captured, it must be a root target in your build graph (i.e.: it may not be consumed by other targets).