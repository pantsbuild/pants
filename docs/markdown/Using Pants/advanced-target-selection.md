---
title: "Advanced target selection"
slug: "advanced-target-selection"
excerpt: "Alternative techniques to tell Pants which files/targets to run on."
hidden: false
createdAt: "2020-05-11T20:10:29.560Z"
updatedAt: "2022-02-08T23:44:44.463Z"
---
See [File arguments vs. target arguments](doc:goals#file-arguments-vs-target-arguments) for the normal techniques for telling Pants what to run on. 

See [Project introspection](doc:project-introspection) for queries that you can run and then pipe into another Pants run, such as running over certain target types.
[block:api-header]
{
  "title": "Running over changed files with `--changed-since`"
}
[/block]
Because Pants understands Git, it can find which files have changed since a certain commit through the `--changed-since` option.

For example, to lint all uncommitted files, run:

```bash
./pants --changed-since=HEAD lint
```

To run against another branch, run:

```bash
./pants --changed-since=origin/main lint
```

By default, `--changed-since` will only run over files directly changed. Often, though, you will want to run over any [dependees](doc:project-introspection) of those changed files, meaning any targets that depend on the changed files. Use ` --changed-dependees=direct` or ` --changed-dependees=transitive` for this:

```bash
$ ./pants \
  --changed-since=origin/main \
  --changed-dependees=transitive \
  test
```
[block:callout]
{
  "type": "warning",
  "title": "Using a version control system other than Git?",
  "body": "Please message us on Slack or open a GitHub issue (see [Community](doc:getting-help)). We would be happy to look into adding support for your VCS, such as helping you with a PR to add support."
}
[/block]

[block:api-header]
{
  "title": "Tags: annotating targets"
}
[/block]
Every target type has a field called `tags`, which allows you to add a sequence of strings. The strings can be whatever you'd like, such as `"integration_test"`.
[block:code]
{
  "codes": [
    {
      "code": "python_tests(\n    name=\"integration\",\n    sources=[\"*_integration_test.py\"],\n    tags=[\"skip_lint\", \"integration_test\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
You can then filter by tags with the global `--tag` [option](doc:reference-global#section-tag), like this:

```bash
./pants --tag=integration_test list ::
```

To exclude certain tags, prefix with a `-`:

```bash
./pants --tag='-integration_test' list ::
```

You can even combine multiple includes and excludes:

```bash
./pants --tag='+type_checked,skip_lint' --tag='-integration_test' list ::
```
[block:api-header]
{
  "title": "`--spec-files`"
}
[/block]
The global option `--spec-files` allows you to pass a file containing target addresses and/or file names/globs to Pants.

Each entry must be separated by a new line.

For example:
[block:code]
{
  "codes": [
    {
      "code": "$ ./pants --spec-files=targets.txt list",
      "language": "text",
      "name": "Shell"
    },
    {
      "code": "helloworld/lang/*.py\nhelloworld/util\nhelloworld/util:tests",
      "language": "text",
      "name": "targets.txt"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: centralized allow/block lists",
  "body": "Whereas `tags` are useful for _decentralized_ allow/block lists, `--spec-files` is useful when you want to define one single list of targets or files."
}
[/block]

[block:api-header]
{
  "title": "Piping to other Pants runs"
}
[/block]
To pipe a Pants run, use your shell's `|` pipe operator and `xargs`:

```bash
./pants dependees helloworld/util | xargs ./pants  list
```

You can, of course, pipe multiple times:

```bash
$ ./pants dependees helloworld/util | \
   xargs ./pants filter --target-type=python_source | \
   xargs ./pants lint
```
[block:callout]
{
  "type": "info",
  "title": "Alternative: use `--spec-files`",
  "body": "Sometimes, you may want to reuse the output of a Pants run for multiple subsequent Pants runs. Rather than repeating `xargs` multiple times, you can generate a file through stdout redirection and `--spec-files`.\n\nFor example:\n\n```bash\n$ ./pants dependencies helloworld/util > util_dependencies.txt\n$ ./pants --spec-files=util_dependencies.txt lint\n```\n\nIf you don't want to save the output to an actual file—such as to not pollute version control—you can use a variable and a named pipe:\n\n```bash\n$ TARGETS=$(./pants dependencies helloworld/util)\n$ ./pants --spec-files=<(echo $TARGETS) lint\n```"
}
[/block]

[block:api-header]
{
  "title": "Sharding the input targets"
}
[/block]
You can leverage shell piping to partition the input targets into multiple shards. 

For example, to split your Python tests into 10 shards, and select shard 0:

```bash
./pants list :: | xargs ./pants filter --target-type=python_test | awk 'NR % 10 == 0' | ./pants test
```