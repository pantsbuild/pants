---
title: "Project introspection"
slug: "project-introspection"
excerpt: "Finding insights in your project."
hidden: false
createdAt: "2020-05-11T09:10:16.427Z"
updatedAt: "2022-04-05T03:00:53.427Z"
---
Pants provides several goals to provide insights into your project's structure.

[block:embed]
{
  "html": "<iframe class=\"embedly-embed\" src=\"//cdn.embedly.com/widgets/media.html?src=https%3A%2F%2Fwww.youtube.com%2Fembed%2FIpEv5cWfyko%3Ffeature%3Doembed&display_name=YouTube&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DIpEv5cWfyko&image=https%3A%2F%2Fi.ytimg.com%2Fvi%2FIpEv5cWfyko%2Fhqdefault.jpg&key=f2aa6fc3595946d0afc3d76cbbd25dc3&type=text%2Fhtml&schema=youtube\" width=\"640\" height=\"480\" scrolling=\"no\" title=\"YouTube embed\" frameborder=\"0\" allow=\"autoplay; fullscreen\" allowfullscreen=\"true\"></iframe>",
  "url": "https://www.youtube.com/watch?v=IpEv5cWfyko",
  "title": "Pants Build 2: Project introspection and dependency inference",
  "favicon": "https://www.youtube.com/s/desktop/d9bba4ed/img/favicon.ico",
  "image": "https://i.ytimg.com/vi/IpEv5cWfyko/hqdefault.jpg"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: Use `xargs` to pipe these goals into other Pants commands",
  "body": "For example:\n\n```bash\n$ ./pants dependees project/util.py | xargs ./pants test\n```\n\nSee [Advanced target selection](doc:advanced-target-selection) for more info and other techniques to use the results."
}
[/block]

[block:api-header]
{
  "title": "`list` - find your project's targets"
}
[/block]
`list` will find all targets that match the arguments.

For example, to show all targets in your project:

```bash
❯ ./pants list ::
//:ansicolors
//:setuptools
helloworld:lib
helloworld:pex_binary
helloworld/__init__.py:lib
helloworld/main.py:lib
...
```

You can specify a file, which will find the target(s) owning that file:

```bash
❯ ./pants list helloworld/greet/greeting_test.py
helloworld/greet/greeting_test.py:tests
```
[block:api-header]
{
  "title": "`filter` - find targets that match a predicate"
}
[/block]
`filter` is like `list`, but will only include targets that match the predicate(s).

Specify a predicate by using one of the below `filter` options, like `--target-type`. You can use a comma to OR multiple values, meaning that at least one member must be matched. You can repeat the option multiple times to AND each filter. You can prefix the filter with `-` to negate the filter, meaning that the target must not be true for the filter.

Some examples:

```bash
# Only `python_source` targets.
./pants filter --target-type=python_source ::

# `python_source` or `python_test` targets.
./pants filter --target-type='python_source,python_test' ::

# Any target except for `python_source` targets
./pants filter --target-type='-python_source' ::
```

### `filter --target-type`

Each value should be the name of a target type, e.g. `python_source` or `resource`. Run `./pants help targets` to see what targets are registered.

### `filter --address-regex`

Regex strings for the address, such as `^dir` or `:util$`.

### `filter --tag-regex`

Regex strings for the `tags` field. Alternatively, you can use the global `--tags` option, which uses exact string matches instead of regex. See [Advanced target selection](doc:advanced-target-selection).
[block:api-header]
{
  "title": "`dependencies` - find a target's dependencies"
}
[/block]
Use `dependencies` to list all targets used directly by a target.

```bash
❯ ./pants dependencies helloworld:pex_binary
helloworld/main.py:lib
```

You can specify a file, which will run on the target(s) owning that file:

```bash
❯ ./pants dependencies helloworld/main.py:lib
//:ansicolors
helloworld/greet/greeting.py:lib
helloworld/main.py:lib
```

To include transitive dependencies—meaning the dependencies of the direct dependencies—use `--transitive`:

```bash
❯ ./pants dependencies --transitive helloworld/main.py:lib
//:ansicolors
//:setuptools
//:types-setuptools
helloworld/greet/greeting.py:lib
helloworld/greet:translations
helloworld/main.py:lib
helloworld/translator/translator.py:lib
```
[block:api-header]
{
  "title": "`dependees` - find which targets depend on a target"
}
[/block]
The `dependees` goal finds all targets that directly depend on the target you specify.

```bash
❯ ./pants dependees //:ansicolors
helloworld/main.py:lib
```

You can specify a file, which will run on the target(s) owning that file:

```
❯ ./pants dependees helloworld/translator/translator.py
helloworld/greet/greeting.py:lib
helloworld/translator:lib
helloworld/translator/translator_test.py:tests
```

To include transitive dependees—meaning targets that don't directly depend on your target, but which depend on a target that does directly use your target—use `--transitive`:

```bash
❯ ./pants dependees --transitive helloworld/translator/translator.py
helloworld:lib
helloworld:pex_binary
helloworld/main.py:lib
helloworld/greet:lib
...
```

To include the original target itself, use `--closed`:

```bash
❯ ./pants dependees --closed //:ansicolors
//:ansicolors
helloworld/main.py:lib
```
[block:api-header]
{
  "title": "`filedeps` - find which files a target owns"
}
[/block]
`filedeps` outputs all of the files belonging to a target, based on its `sources` field.

```bash
❯ ./pants filedeps helloworld/greet:lib
helloworld/greet/BUILD
helloworld/greet/__init__.py
helloworld/greet/greeting.py
```

To output absolute paths, use the option `--absolute`:

```bash
$ ./pants filedeps --absolute helloworld/util:util
/Users/pantsbuild/example-python/helloworld/greet/BUILD
/Users/pantsbuild/example-python/helloworld/greet/__init__.py
/Users/pantsbuild/example-python/helloworld/greet/greeting.py
```

To include the files used by dependencies (including transitive dependencies), use `--transitive`:

```bash
$ ./pants filedeps --transitive helloworld/util:util
BUILD
helloworld/greet/BUILD
helloworld/greet/__init__.py
helloworld/greet/greeting.py
helloworld/greet/translations.json
...
```
[block:api-header]
{
  "title": "`peek` - programmatically inspect a target"
}
[/block]
`peek` outputs JSON for each target specified.

```bash
$ ./pants peek helloworld/util:tests
[
  {
    "address": "helloworld/util:tests",
    "target_type": "python_tests",
    "dependencies": null,
    "description": null,
    "interpreter_constraints": null,
    "skip_black": false,
    "skip_docformatter": false,
    "skip_flake8": true,
    "skip_isort": false,
    "skip_mypy": false,
    "sources": [
      "*.py",
      "*.pyi",
      "!test_*.py",
      "!*_test.py",
      "!tests.py",
      "!conftest.py",
      "!test_*.pyi",
      "!*_test.pyi",
      "!tests.pyi"
    ],
    "tags": null
  }
]
```

You can use `--exclude-defaults` for less verbose output:

```bash
$ ./pants peek --exclude-defaults helloworld/util:tests
[
  {
    "address": "helloworld/util:tests",
    "target_type": "python_tests",
    "skip_flake8": true,
  }
]
```
[block:callout]
{
  "type": "info",
  "title": "Piping peek output into jq",
  "body": "`peek` can be particularly useful when paired with [JQ](https://stedolan.github.io/jq/) to query the JSON. For example, you can combine `./pants peek` with JQ to find all targets where you set the field `skip_flake8=True`:\n\n```bash\n$ ./pants peek :: | jq -r '.[] | select(.skip_flake8 == true) | .[\"address\"]'\nhelloworld/greet:lib\nhelloworld/greet:tests\nhelloworld/util:lib\n```"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Piping other introspection commands into `./pants peek`",
  "body": "Some introspection goals, such as `filter`, `dependencies` and `dependees` emit a flat list of target addresses. It's often useful to expand each of those into a full JSON structure with detailed properties of each target, by piping to `./pants peek`:\n\n```bash\n./pants dependees  helloworld/main.py:lib | xargs ./pants peek --exclude-defaults\n[\n  {\n    \"address\": \"helloworld:lib\",\n    \"target_type\": \"python_sources\",\n    \"dependencies\": [\n      \"helloworld/__init__.py:lib\",\n      \"helloworld/main.py:lib\"\n    ],\n    \"sources\": [\n      \"helloworld/__init__.py\",\n      \"helloworld/main.py\"\n    ]\n  },\n  {\n    \"address\": \"helloworld:pex_binary\",\n    \"target_type\": \"pex_binary\",\n    \"dependencies\": [\n      \"helloworld/main.py:lib\"\n    ],\n    \"entry_point\": {\n      \"module\": \"main.py\",\n      \"function\": null\n    }\n  }\n]\n```"
}
[/block]

[block:api-header]
{
  "title": "`paths` - find dependency paths"
}
[/block]
`paths` emits a list of all dependency paths between two targets:

```bash
$ ./pants paths --from=helloworld/main.py --to=helloworld/translator/translator.py
[
  [
    "helloworld/main.py:lib",
    "helloworld/greet/greeting.py:lib",
    "helloworld/translator/translator.py:lib"
  ]
]
```
[block:api-header]
{
  "title": "`count-loc` - count lines of code"
}
[/block]
`count-loc` counts the lines of code of the specified files by running the [Succinct Code Counter](https://github.com/boyter/scc) tool.
[block:code]
{
  "codes": [
    {
      "code": "$ ./pants count-loc ::\n───────────────────────────────────────────────────────────────────────────────\nLanguage                 Files     Lines   Blanks  Comments     Code Complexity\n───────────────────────────────────────────────────────────────────────────────\nPython                    1690    618679    23906      7270   587503      18700\nHTML                        61      6522      694        67     5761          0\nJSON                        36     18755        6         0    18749          0\nYAML                        30      2451        4        19     2428          0\nJavaScript                   6       671       89         8      574         32\nCSV                          1         2        0         0        2          0\nJSONL                        1         4        0         0        4          0\nJinja                        1        11        0         0       11          2\nShell                        1        13        2         2        9          4\nTOML                         1       146        5         0      141          0\n───────────────────────────────────────────────────────────────────────────────\nTotal                     1828    647254    24706      7366   615182      18738\n───────────────────────────────────────────────────────────────────────────────\nEstimated Cost to Develop $22,911,268\nEstimated Schedule Effort 50.432378 months\nEstimated People Required 53.813884\n───────────────────────────────────────────────────────────────────────────────",
      "language": "shell"
    }
  ]
}
[/block]

[block:code]
{
  "codes": [
    {
      "code": "$ ./pants count-loc '**/*.py' '**/*.proto'\n───────────────────────────────────────────────────────────────────────────────\nLanguage                 Files     Lines   Blanks  Comments     Code Complexity\n───────────────────────────────────────────────────────────────────────────────\nPython                      13       155       50        22       83          5\nProtocol Buffers             1        11        3         2        6          0\n───────────────────────────────────────────────────────────────────────────────\nTotal                       14       166       53        24       89          5\n───────────────────────────────────────────────────────────────────────────────",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
SCC has [dozens of options](https://github.com/boyter/scc#usage). You can pass through options by either setting `--scc-args` or using `--` at the end of your command, like this:

```bash
./pants count-loc '**' -- --no-cocomo
```
[block:callout]
{
  "type": "warning",
  "title": "See unexpected results? Set `pants_ignore`.",
  "body": "By default, Pants will ignore all globs specified in your `.gitignore`, along with `dist/` and any hidden files.\n\nTo ignore additional files, add to the global option `pants_ignore` in your `pants.toml`, using the same [syntax](https://git-scm.com/docs/gitignore) as `.gitignore` files. \n\nFor example:\n\n```toml\n[GLOBAL]\npants_ignore.add = [\"/ignore_this_dir/\"]\n```"
}
[/block]