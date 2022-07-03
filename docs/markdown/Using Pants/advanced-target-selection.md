---
title: "Advanced target selection"
slug: "advanced-target-selection"
excerpt: "Alternative techniques to tell Pants which files/targets to run on."
hidden: false
createdAt: "2020-05-11T20:10:29.560Z"
updatedAt: "2022-02-08T23:44:44.463Z"
---
See [File arguments vs. target arguments](doc:goals#goal-arguments) for the normal techniques for telling Pants what to run on. 

See [Project introspection](doc:project-introspection) for queries that you can run and then pipe into another Pants run, such as running over certain target types.

Running over changed files with `--changed-since`
-------------------------------------------------

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
❯ ./pants \
  --changed-since=origin/main \
  --changed-dependees=transitive \
  test
```

Tags: annotating targets
------------------------

Every target type has a field called `tags`, which allows you to add a sequence of strings. The strings can be whatever you'd like, such as `"integration_test"`.

```python BUILD
python_tests(
    name="integration",
    sources=["*_integration_test.py"],
    tags=["skip_lint", "integration_test"],
)
```

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

`--spec-files`
--------------

The global option `--spec-files` allows you to pass a file containing target addresses and/or file names/globs to Pants.

Each entry must be separated by a new line.

For example:

```text Shell
$ ./pants --spec-files=targets.txt list
```
```text targets.txt
helloworld/lang/*.py
helloworld/util
helloworld/util:tests
```

> 📘 Tip: centralized allow/block lists
> 
> Whereas `tags` are useful for _decentralized_ allow/block lists, `--spec-files` is useful when you want to define one single list of targets or files.

Piping to other Pants runs
--------------------------

To pipe a Pants run, use your shell's `|` pipe operator and `xargs`:

```bash
./pants dependees helloworld/util | xargs ./pants  list
```

You can, of course, pipe multiple times:

```bash
$ ./pants dependees helloworld/util | \
   xargs ./pants list --filter-target-type=python_source | \
   xargs ./pants lint
```

> 📘 Alternative: use `--spec-files`
> 
> Sometimes, you may want to reuse the output of a Pants run for multiple subsequent Pants runs. Rather than repeating `xargs` multiple times, you can generate a file through stdout redirection and `--spec-files`.
> 
> For example:
> 
> ```bash
> $ ./pants dependencies helloworld/util > util_dependencies.txt
> $ ./pants --spec-files=util_dependencies.txt lint
> ```
> 
> If you don't want to save the output to an actual file—such as to not pollute version control—you can use a variable and a named pipe:
> 
> ```bash
> $ TARGETS=$(./pants dependencies helloworld/util)
> $ ./pants --spec-files=<(echo $TARGETS) lint
> ```

Sharding the input targets
--------------------------

You can leverage shell piping to partition the input targets into multiple shards. 

For example, to split your Python tests into 10 shards, and select shard 0:

```bash
./pants list :: | xargs ./pants list --filter-target-type=python_test | awk 'NR % 10 == 0' | ./pants test
```
