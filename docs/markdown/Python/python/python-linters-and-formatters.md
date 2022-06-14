---
title: "Linters and formatters"
slug: "python-linters-and-formatters"
excerpt: "How to activate and use the Python linters and formatters bundled with Pants."
hidden: false
createdAt: "2020-03-03T00:57:15.994Z"
updatedAt: "2022-04-03T02:01:57.201Z"
---
[block:callout]
{
  "type": "success",
  "title": "Benefit of Pants: consistent interface",
  "body": "`./pants lint` and `./pants fmt` will consistently and correctly run all your linters and formatters. No need to remember how to invoke each tool, and no need to write custom scripts. \n\nThis consistent interface even works with multiple languages, like running Python linters at the same time as Go, Shell, Java, and Scala."
}
[/block]

[block:callout]
{
  "type": "success",
  "title": "Benefit of Pants: concurrency",
  "body": "Pants does several things to speed up running formatters and linters:\n\n* Automatically configures tools that support concurrency (e.g. a `--jobs` option) based on your number of cores and what else is already running.\n* Runs everything in parallel with the `lint` goal (although not the `fmt` goal, which pipes the results of one formatter to the next for correctness).\n* Runs in batches of 256 files by default, which gives parallelism even for tools that don't have a `--jobs` option. This also increases cache reuse."
}
[/block]

[block:api-header]
{
  "title": "Activating linters and formatters"
}
[/block]
Linter/formatter support is implemented in separate [backends](doc:enabling-backends) so that they are easy to opt in to individually:
[block:parameters]
{
  "data": {
    "h-0": "Backend",
    "h-1": "Tool",
    "0-0": "`pants.backend.python.lint.bandit`",
    "0-1": "[Bandit](https://bandit.readthedocs.io/en/latest/): security linter",
    "1-0": "`pants.backend.python.lint.black`",
    "1-1": "[Black](https://black.readthedocs.io/en/stable/): code formatter",
    "2-0": "`pants.backend.python.lint.docformatter`",
    "2-1": "[Docformatter](https://pypi.org/project/docformatter/): docstring formatter",
    "3-0": "`pants.backend.python.lint.flake8`",
    "3-1": "[Flake8](https://flake8.pycqa.org/en/latest/): style and bug linter",
    "4-0": "`pants.backend.python.lint.isort`",
    "4-1": "[isort](https://readthedocs.org/projects/isort/): import statement formatter",
    "5-0": "`pants.backend.python.lint.pylint`",
    "5-1": "[Pylint](https://pylint.pycqa.org/): style and bug linter",
    "6-0": "`pants.backend.python.lint.yapf`",
    "6-1": "[Yapf](https://github.com/google/yapf): code formatter",
    "7-0": "`pants.backend.experimental.python.lint.autoflake`",
    "7-1": "[Autoflake](https://github.com/myint/autoflake): remove unused imports",
    "8-0": "`pants.backend.experimental.python.lint.pyupgrade`",
    "8-1": "[Pyupgrade](https://github.com/asottile/pyupgrade): automatically update code to use modern Python idioms like `f-strings`"
  },
  "cols": 2,
  "rows": 9
}
[/block]
To enable, add the appropriate backends in `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\n...\nbackend_packages = [\n  'pants.backend.python',\n  'pants.backend.python.lint.black',\n  'pants.backend.python.lint.isort',\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
You should now be able to run `./pants lint`, and possibly `./pants fmt`:

```
$ ./pants lint src/py/project.py
17:54:32.51 [INFO] Completed: lint - Flake8 succeeded.
17:54:32.70 [INFO] Completed: lint - Black succeeded.
All done! ✨ 🍰 ✨
1 file would be left unchanged.

17:54:33.91 [INFO] Completed: lint - isort succeeded.

✓ Black succeeded.
✓ Flake8 succeeded.
✓ isort succeeded.
```
[block:callout]
{
  "type": "info",
  "title": "How to activate MyPy",
  "body": "MyPy is run with the [check goal](doc:python-check-goal), rather than `lint`."
}
[/block]

[block:api-header]
{
  "title": "Configuring the tools, e.g. adding plugins"
}
[/block]
You can configure each formatter and linter using these options:
[block:parameters]
{
  "data": {
    "h-0": "Option",
    "h-1": "What it does",
    "0-0": "`version`",
    "0-1": "E.g. `flake8==3.8.0`.",
    "1-0": "`extra_requirements`",
    "1-1": "Any additional dependencies to install, such as any plugins.",
    "2-0": "`interpreter_constraints`",
    "2-1": "What interpreter to run the tool with. (`bandit`, `flake8`, and `pylint` instead determine this based on your [code's interpreter constraints](doc:python-interpreter-compatibility).)",
    "3-0": "`args`",
    "3-1": "Any command-line arguments you want to pass to the tool.",
    "4-0": "`config`",
    "4-1": "Path to a config file. Useful if the file is in a non-standard location such that it cannot be auto-discovered.",
    "5-0": "`lockfile`",
    "5-1": "Path to a custom lockfile if the default does not work, or `\"<none>\"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles)."
  },
  "cols": 2,
  "rows": 6
}
[/block]
For example:
[block:code]
{
  "codes": [
    {
      "code": "[docformatter]\nargs = [\"--wrap-summaries=100\", \"--wrap-descriptions=100\"]\n\n[flake8]\n# Load a config file in a non-standard location.\nconfig = \"build-support/flake8\"\n# Change the version and add a custom plugin. Because we do this, we\n# use a custom lockfile.\nversion = \"flake8==3.8.0\"\nextra_requirements.add = [\"flake8-2020\"]\nlockfile = \"3rdparty/flake8_lockfile.txt\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Run `./pants help-advanced black`, `./pants help-advanced flake8`, and so on for more information.
[block:callout]
{
  "type": "info",
  "title": "Config files are normally auto-discovered",
  "body": "For tools that autodiscover config files—such as Black, isort, Flake8, and Pylint—Pants will include any relevant config files in the process's sandbox when running the tool.\n\nIf your config file is in a non-standard location, you must instead set the `--config` option, e.g. `[isort].config`. This will ensure that the config file is included in the process's sandbox and Pants will instruct the tool to load the config."
}
[/block]

[block:api-header]
{
  "title": "Running only certain formatters or linters"
}
[/block]
To temporarily skip a tool, use the `--skip` option for that tool. For example, run:

```bash
❯  ./pants --black-skip --flake8-skip lint ::
```

You can also use the `--lint-only` and `--fmt-only` options with the names of the tools:

```bash
❯ ./pants lint --only=black ::

# To run several, you can use either approach:
❯ ./pants fmt --only=black --only=isort ::
❯ ./pants fmt --only='["black", "isort"]' ::
```

You can also skip for certain targets with the `skip_<tool>` fields, which can be useful for [incrementally adopting new tools](https://www.youtube.com/watch?v=BOhcdRsmv0s). For example:
[block:code]
{
  "codes": [
    {
      "code": "python_sources(\n    name=\"lib\",\n    # Skip Black for all non-test files in this folder.\n    skip_black=True,\n    overrides={\n        \"strutil.py\": {\"skip_flake8\": True},\n        (\"docutil.py\", \"dirutil.py\"): {\"skip_isort\": True},\n    },\n)\n\npython_tests(\n    name=\"tests\",\n    # Skip isort for all the test files in this folder.\n    skip_isort=True,\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
When you run `./pants fmt` and `./pants lint`, Pants will ignore any files belonging to skipped targets.
[block:api-header]
{
  "title": "Tip: only run over changed files"
}
[/block]
With formatters and linters, there is usually no need to rerun on files that have not changed.

Use the option `--changed-since` to get much better performance, like this:

```bash
❯ ./pants --changed-since=HEAD fmt
```

or

```bash
❯ ./pants --changed-since=main lint
```

Pants will find which files have changed and only run over those files. See [Advanced target selection](doc:advanced-target-selection) for more information.
[block:api-header]
{
  "title": "Tips for specific tools"
}
[/block]
### Order of `backend_packages` matters for `fmt`

Pants will run formatters in the order in which they appear in the `backend_packages` option. 

For example, you likely want to put Autoflake (which removes unused imports) before Black and Isort, which will format your import statements.
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n    # Note that we want Autoflake to run before Black and isort, \n    # so it must appear first.\n    \"pants.backend.python.experimental.autoflake\",\n    \"pants.backend.python.black\",\n    \"pants.backend.python.isort\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### Bandit and Flake8: report files

Flake8 and Bandit can both generate report files saved to disk. 

For Pants to properly preserve the reports, instruct both tools to write to the `reports/` folder by updating their config files or `--flake8-args` and `--bandit-args`. For example, in your `pants.toml`:

```toml
[bandit]
args = ["--output=reports/report.txt"]

[flake8]
args = ["--output-file=reports/report.txt"]
```

Pants will copy all reports into the folder `dist/lint/<linter_name>`.

### Pylint and Flake8: how to add first-party plugins

See [`[pylint].source_plugins`](https://www.pantsbuild.org/docs/reference-pylint#section-source-plugins) and [`[flake8].source_plugins`](https://www.pantsbuild.org/docs/reference-flake8#section-source-plugins) for instructions to add plugins written by you.


### Bandit: less verbose logging

Bandit output can be extremely verbose, including on successful runs. You may want to use its `--quiet` option, which will turn off output for successful runs but keep it for failures. 

For example, you can set this in your `pants.toml`:

```toml
[bandit]
args = ["--quiet"]
```

### Black and isort can work together

If you use both `black` and `isort`, you most likely will need to tell `isort` to work in a mode compatible with `black`. It is also a good idea to ensure they use the same line length. This requires tool specific configuration, which could go into `pyproject.toml` for example:

```toml
# pyproject.toml
[tool.isort]
profile = "black"
line_length = 100

[tool.black]
line-length = 100
```

### Pyupgrade: specify which Python version to target

You must tell Pyupgrade which version of Python to target, like this:

```toml
# pants.toml
[pyupgrade]
args = ["--py36-plus"]
```

### Autoflake and Pyupgrade are experimental

These tools are marked experimental because we are debating adding a new goal called `fix` and running them with `fix` rather than `fmt`. The tools are safe to use, other than possibly changing how you invoke them in the future.

We invite you to [weigh in with what you think](https://github.com/pantsbuild/pants/issues/13504)!

### isort: possible issues with its import classifier algorithm

Some Pants users had to explicitly set `default_section = "THIRDPARTY"` to get iSort 5 to correctly classify their first-party imports, even though this is the default value.

They report that this config works for them:

```toml
# pyproject.toml
[tool.isort]
known_first_party = ["my_org"]
default_section = "THIRDPARTY"
```

You may also want to try downgrading to iSort 4.x by setting `version = "isort>=4.6,<5"` in the `[isort]` options scope.