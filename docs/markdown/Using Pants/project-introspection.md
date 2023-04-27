---
title: "Project introspection"
slug: "project-introspection"
excerpt: "Finding insights in your project."
hidden: false
createdAt: "2020-05-11T09:10:16.427Z"
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

> 📘 Tip: Use `xargs` to pipe these goals into other Pants commands
> 
> For example:
> 
> ```bash
> $ pants dependents project/util.py | xargs pants test
> ```
> 
> See [Advanced target selection](doc:advanced-target-selection) for more info and other techniques to use the results.

`list` - find your project's targets
------------------------------------

`list` will find all targets that match the arguments.

For example, to show all targets in your project:

```bash
❯ pants list ::
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
❯ pants list helloworld/greet/greeting_test.py
helloworld/greet/greeting_test.py:tests
```

`list` often works well when paired with the `--filter` options from
[Advanced Target Selection](doc:advanced-target-selection), e.g.
`pants --filter-target-type=python_test list ::` to find all your `python_test` targets.

`dependencies` - find a target's dependencies
---------------------------------------------

Use `dependencies` to list all targets used directly by a target.

```bash
❯ pants dependencies helloworld:pex_binary
helloworld/main.py:lib
```

You can specify a file, which will run on the target(s) owning that file:

```bash
❯ pants dependencies helloworld/main.py:lib
//:ansicolors
helloworld/greet/greeting.py:lib
helloworld/main.py:lib
```

To include transitive dependencies—meaning the dependencies of the direct dependencies—use `--transitive`:

```bash
❯ pants dependencies --transitive helloworld/main.py:lib
//:ansicolors
//:setuptools
//:types-setuptools
helloworld/greet/greeting.py:lib
helloworld/greet:translations
helloworld/main.py:lib
helloworld/translator/translator.py:lib
```

`dependents` - find which targets depend on a target
----------------------------------------------------

The `dependents` goal finds all targets that directly depend on the target you specify.

```bash
❯ pants dependents //:ansicolors
helloworld/main.py:lib
```

You can specify a file, which will run on the target(s) owning that file:

```
❯ pants dependents helloworld/translator/translator.py
helloworld/greet/greeting.py:lib
helloworld/translator:lib
helloworld/translator/translator_test.py:tests
```

To include transitive dependents — meaning targets that don't directly depend on your target, but which depend on a target that does directly use your target — use `--transitive`:

```bash
❯ pants dependents --transitive helloworld/translator/translator.py
helloworld:lib
helloworld:pex_binary
helloworld/main.py:lib
helloworld/greet:lib
...
```

To include the original target itself, use `--closed`:

```bash
❯ pants dependents --closed //:ansicolors
//:ansicolors
helloworld/main.py:lib
```

`filedeps` - find which files a target owns
-------------------------------------------

`filedeps` outputs all of the files belonging to a target, based on its `sources` field.

```bash
❯ pants filedeps helloworld/greet:lib
helloworld/greet/BUILD
helloworld/greet/__init__.py
helloworld/greet/greeting.py
```

To output absolute paths, use the option `--absolute`:

```bash
$ pants filedeps --absolute helloworld/util:util
/Users/pantsbuild/example-python/helloworld/greet/BUILD
/Users/pantsbuild/example-python/helloworld/greet/__init__.py
/Users/pantsbuild/example-python/helloworld/greet/greeting.py
```

To include the files used by dependencies (including transitive dependencies), use `--transitive`:

```bash
$ pants filedeps --transitive helloworld/util:util
BUILD
helloworld/greet/BUILD
helloworld/greet/__init__.py
helloworld/greet/greeting.py
helloworld/greet/translations.json
...
```

`peek` - programmatically inspect a target
------------------------------------------

`peek` outputs JSON for each target specified.

```bash
$ pants peek helloworld/util:tests
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
$ pants peek --exclude-defaults helloworld/util:tests
[
  {
    "address": "helloworld/util:tests",
    "target_type": "python_tests",
    "skip_flake8": true,
  }
]
```

> 📘 Piping peek output into jq
> 
> `peek` can be particularly useful when paired with [JQ](https://stedolan.github.io/jq/) to query the JSON. For example, you can combine `pants peek` with JQ to find all targets where you set the field `skip_flake8=True`:
> 
> ```bash
> $ pants peek :: | jq -r '.[] | select(.skip_flake8 == true) | .["address"]'
> helloworld/greet:lib
> helloworld/greet:tests
> helloworld/util:lib
> ```

> 📘 Piping other introspection commands into `pants peek`
> 
> Some introspection goals, such as `filter`, `dependencies` and `dependents` emit a flat list of target addresses. It's often useful to expand each of those into a full JSON structure with detailed properties of each target, by piping to `pants peek`:
> 
> ```bash
> pants dependents  helloworld/main.py:lib | xargs pants peek --exclude-defaults
> [
>   {
>     "address": "helloworld:lib",
>     "target_type": "python_sources",
>     "dependencies": [
>       "helloworld/__init__.py:lib",
>       "helloworld/main.py:lib"
>     ],
>     "sources": [
>       "helloworld/__init__.py",
>       "helloworld/main.py"
>     ]
>   },
>   {
>     "address": "helloworld:pex_binary",
>     "target_type": "pex_binary",
>     "dependencies": [
>       "helloworld/main.py:lib"
>     ],
>     "entry_point": {
>       "module": "main.py",
>       "function": null
>     }
>   }
> ]
> ```

`paths` - find dependency paths
-------------------------------

`paths` emits a list of all dependency paths between two targets:

```bash
$ pants paths --from=helloworld/main.py --to=helloworld/translator/translator.py
[
  [
    "helloworld/main.py:lib",
    "helloworld/greet/greeting.py:lib",
    "helloworld/translator/translator.py:lib"
  ]
]
```

`count-loc` - count lines of code
---------------------------------

`count-loc` counts the lines of code of the specified files by running the [Succinct Code Counter](https://github.com/boyter/scc) tool.

```shell
❯ pants count-loc ::
───────────────────────────────────────────────────────────────────────────────
Language                 Files     Lines   Blanks  Comments     Code Complexity
───────────────────────────────────────────────────────────────────────────────
Python                    1690    618679    23906      7270   587503      18700
HTML                        61      6522      694        67     5761          0
JSON                        36     18755        6         0    18749          0
YAML                        30      2451        4        19     2428          0
JavaScript                   6       671       89         8      574         32
CSV                          1         2        0         0        2          0
JSONL                        1         4        0         0        4          0
Jinja                        1        11        0         0       11          2
Shell                        1        13        2         2        9          4
TOML                         1       146        5         0      141          0
───────────────────────────────────────────────────────────────────────────────
Total                     1828    647254    24706      7366   615182      18738
───────────────────────────────────────────────────────────────────────────────
Estimated Cost to Develop $22,911,268
Estimated Schedule Effort 50.432378 months
Estimated People Required 53.813884
───────────────────────────────────────────────────────────────────────────────
```

SCC has [dozens of options](https://github.com/boyter/scc#usage). You can pass through options by either setting `--scc-args` or using `--` at the end of your command, like this:

```bash
pants count-loc :: -- --no-cocomo
```

> 🚧 See unexpected results? Set `pants_ignore`.
> 
> By default, Pants will ignore all globs specified in your `.gitignore`, along with `dist/` and any hidden files.
> 
> To ignore additional files, add to the global option `pants_ignore` in your `pants.toml`, using the same [syntax](https://git-scm.com/docs/gitignore) as `.gitignore` files. 
> 
> For example:
> 
> ```toml pants.toml
> [GLOBAL]
> pants_ignore.add = ["/ignore_this_dir/"]
> ```
