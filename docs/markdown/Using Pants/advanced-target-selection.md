---
title: "Advanced target selection"
slug: "advanced-target-selection"
excerpt: "Alternative techniques to tell Pants which files/targets to run on."
hidden: false
createdAt: "2020-05-11T20:10:29.560Z"
---
See [Goal arguments](doc:goals#goal-arguments) for the normal techniques for telling Pants what to
run on. 

See [Project introspection](doc:project-introspection) for queries that you can run and then pipe
into another Pants run, such as finding the dependencies of a target or file.

Running over changed files with `--changed-since`
-------------------------------------------------

Because Pants understands Git, it can find which files have changed since a certain commit through the `--changed-since` option.

For example, to lint all uncommitted files, run:

```bash
pants --changed-since=HEAD lint
```

To run against another branch, run:

```bash
pants --changed-since=origin/main lint
```

By default, `--changed-since` will only run over files directly changed. Often, though, you will want to run over any [dependents](doc:project-introspection) of those changed files, meaning any targets that depend on the changed files. Use ` --changed-dependents=direct` or ` --changed-dependents=transitive` for this:

```bash
❯ pants \
  --changed-since=origin/main \
  --changed-dependents=transitive \
  test
```

`filter` options
----------------

Use filters to operate on only targets that match the predicate, e.g. only running Python tests.

Specify a predicate by using one of the below `filter` options, like `--filter-target-type`. You
can use a comma to OR multiple values, meaning that at least one member must be matched. You
can repeat the option multiple times to AND each filter. You can prefix the filter with
`-` to negate the filter, meaning that the target must not be true for the filter.

Some examples:

```bash
# Only `python_source` targets.
pants --filter-target-type=python_source list ::

# `python_source` or `python_test` targets.
pants --filter-target-type='python_source,python_test' list ::

# Any target except for `python_source` targets
pants --filter-target-type='-python_source' list ::
```

You can combine multiple filter options in the same run, e.g.:

```bash
pants --filter-target-type='python_test' --filter-address-regex=^integration_tests test ::
```

### `--filter-target-type`

Each value should be the name of a target type, e.g.
`pants --filter-target-type=python_test test ::`.

Run `pants help targets` to see what targets are registered.

### `--filter-address-regex`

Regex strings for the address, such as
`pants --filter-address-regex='^integration_tests$' test ::`.

### `--filter-tag-regex`

Regex strings to match against the `tags` field, such as 
`pants --filter-tag-regex='^skip_lint$' lint ::`.

If you don't need the power of regex, use the simpler `--tag` global option explained below.

Tags: annotating targets
------------------------

Every target type has a field called `tags`, which allows you to add a sequence of strings. The
strings can be whatever you'd like, such as `"integration_test"`.

```python BUILD
python_tests(
    name="integration",
    sources=["*_integration_test.py"],
    tags=["skip_lint", "integration_test"],
)
```

You can then filter by tags with the global `--tag` [option](doc:reference-global#section-tag), like this:

```bash
pants --tag=integration_test list ::
```

To exclude certain tags, prefix with a `-`:

```bash
pants --tag='-integration_test' list ::
```

You can even combine multiple includes and excludes:

```bash
pants --tag='+type_checked,skip_lint' --tag='-integration_test' list ::
```

Use `--filter-tag-regex` instead for more complex queries.

`--spec-files`
--------------

The global option `--spec-files` allows you to pass a file containing target addresses and/or file names/globs to Pants.

Each entry must be separated by a new line.

For example:

```text Shell
$ pants --spec-files=targets.txt list
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
pants dependents helloworld/util | xargs pants  list
```

You can, of course, pipe multiple times:

```bash
# Run over the second-degree dependents of `utils.py`.
❯ pants dependents helloworld/utils.py | \
   xargs pants dependents | \
   xargs pants lint
```

> 📘 Alternative: use `--spec-files`
> 
> Sometimes, you may want to reuse the output of a Pants run for multiple subsequent Pants runs. Rather than repeating `xargs` multiple times, you can generate a file through stdout redirection and `--spec-files`.
> 
> For example:
> 
> ```bash
> $ pants dependencies helloworld/util > util_dependencies.txt
> $ pants --spec-files=util_dependencies.txt lint
> ```
> 
> If you don't want to save the output to an actual file—such as to not pollute version control—you can use a variable and a named pipe:
> 
> ```bash
> $ TARGETS=$(pants dependencies helloworld/util)
> $ pants --spec-files=<(echo $TARGETS) lint
> ```

Sharding the input targets
--------------------------

The `test` goal natively supports sharding input targets into multiple shards. Use the option `--test-shard=k/N`, where k is a non-negative integer less than N. For example, you can split up your CI into three shards with `--shard=0/3`, `--shard=1/3`, and `--shard=2/3`.

For other goals, you can leverage shell piping to partition the input targets into multiple shards. For example, to split your `package` run into 5 shards, and select shard 0:

```bash
pants list :: | awk 'NR % 5 == 0' | xargs pants package
```
