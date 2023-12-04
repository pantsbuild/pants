---
title: "Linters and formatters"
slug: "python-linters-and-formatters"
excerpt: "How to activate and use the Python linters and formatters bundled with Pants."
hidden: false
createdAt: "2020-03-03T00:57:15.994Z"
---
> 👍 Benefit of Pants: consistent interface
>
> `pants lint` and `pants fmt` will consistently and correctly run all your linters and formatters. No need to remember how to invoke each tool, and no need to write custom scripts.
>
> This consistent interface even works with multiple languages, like running Python linters at the same time as Go, Shell, Java, and Scala.

> 👍 Benefit of Pants: concurrency
>
> Pants does several things to speed up running formatters and linters:
>
> - Automatically configures tools that support concurrency (e.g. a `--jobs` option) based on your number of cores and what else is already running.
> - Runs everything in parallel with the `lint` goal (although not the `fmt` goal, which pipes the results of one formatter to the next for correctness).
> - Runs in batches of 256 files by default, which gives parallelism even for tools that don't have a `--jobs` option. This also increases cache reuse.

Activating linters and formatters
---------------------------------

Linter/formatter support is implemented in separate [backends](doc:enabling-backends) so that they are easy to opt in to individually:

| Backend                                       | Tool                                                                                                                       |
|:----------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------|
| `pants.backend.python.lint.bandit`            | [Bandit](https://bandit.readthedocs.io/en/latest/): security linter                                                        |
| `pants.backend.python.lint.black`             | [Black](https://black.readthedocs.io/en/stable/): code formatter                                                           |
| `pants.backend.python.lint.docformatter`      | [Docformatter](https://pypi.org/project/docformatter/): docstring formatter                                                |
| `pants.backend.python.lint.flake8`            | [Flake8](https://flake8.pycqa.org/en/latest/): style and bug linter                                                        |
| `pants.backend.python.lint.isort`             | [isort](https://readthedocs.org/projects/isort/): import statement formatter                                               |
| `pants.backend.python.lint.pydocstyle`        | [Pydocstyle](https://pypi.org/project/pydocstyle/): docstring linter                                                       |
| `pants.backend.python.lint.pylint`            | [Pylint](https://pylint.pycqa.org/): style and bug linter                                                                  |
| `pants.backend.python.lint.yapf`              | [Yapf](https://github.com/google/yapf): code formatter                                                                     |
| `pants.backend.python.lint.autoflake`         | [Autoflake](https://github.com/myint/autoflake): remove unused imports                                                     |
| `pants.backend.python.lint.pyupgrade`         | [Pyupgrade](https://github.com/asottile/pyupgrade): automatically update code to use modern Python idioms like `f-strings` |
| `pants.backend.experimental.python.lint.ruff` | [Ruff](https://beta.ruff.rs/docs/): an extremely fast Python linter, written in Rust.                                      |

To enable, add the appropriate backends in `pants.toml`:

```toml pants.toml
[GLOBAL]
...
backend_packages = [
  'pants.backend.python',
  'pants.backend.python.lint.black',
  'pants.backend.python.lint.isort',
]
```

You should now be able to run `pants lint`, and possibly `pants fmt`:

```
$ pants lint src/py/project.py
17:54:32.51 [INFO] Completed: lint - Flake8 succeeded.
17:54:32.70 [INFO] Completed: lint - Black succeeded.
All done! ✨ 🍰 ✨
1 file would be left unchanged.

17:54:33.91 [INFO] Completed: lint - isort succeeded.

✓ Black succeeded.
✓ Flake8 succeeded.
✓ isort succeeded.
```

> 📘 How to activate MyPy
>
> MyPy is run with the [check goal](doc:python-check-goal), rather than `lint`.

Configuring the tools, for example, adding plugins
------------------------------------------

You can configure each formatter and linter using these options:

| Option                               | What it does                                                                                                                                                                   |
|:-------------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `interpreter_constraints`            | What interpreter to run the tool with. (`bandit`, `flake8`, and `pylint` determine this based on your [code's interpreter constraints](doc:python-interpreter-compatibility).) |
| `args`                               | Any command-line arguments you want to pass to the tool.                                                                                                                       |
| `config`                             | Path to a config file. Useful if the file is in a non-standard location such that it cannot be auto-discovered.                                                                |
| `install_from_resolve`               | Name of a custom resolve to use for tool versions and plugins. See [Lockfiles for tools](doc:python-lockfiles#lockfiles-for-tools).                                            |
| `requirements`                       | Optional subset of requirements to install from the custom resolve for this formatter or linter. See [Lockfiles for tools](doc:python-lockfiles#lockfiles-for-tools).          |

For example:

```toml pants.toml
[docformatter]
args = ["--wrap-summaries=100", "--wrap-descriptions=100"]

[python.resolves]
# A custom resolve that updates the version and adds a custom plugin.
flake8 = "3rdparty/python/flake8.lock"

[flake8]
# Load a config file in a non-standard location.
config = "build-support/flake8"
install_from_resolve = "flake8"
```

Then set up the resolve's inputs:

```python 3rdparty/python/BUILD
python_requirements(
    source="flake8-requirements.txt",
    resolve="flake8",
)
```
```Text 3rdparty/python/flake8-requirements.txt
flake8==6.0.0
flake8-bugbear>=23.3.23
```

And generate its custom lockfile:

```shell Bash
$ pants generate-lockfiles --resolve=flake8
16:00:39.26 [INFO] Completed: Generate lockfile for flake8
16:00:39.29 [INFO] Wrote lockfile for the resolve `flake8` to 3rdparty/python/flake8.lock
```

Run `pants help-advanced black`, `pants help-advanced flake8`, and so on for more information.

> 📘 Config files are normally auto-discovered
>
> For tools that autodiscover config files—such as Black, isort, Flake8, and Pylint—Pants will include any relevant config files in the process's sandbox when running the tool.
>
> If your config file is in a non-standard location, you must instead set the `--config` option, e.g. `[isort].config`. This will ensure that the config file is included in the process's sandbox and Pants will instruct the tool to load the config.

Running only certain formatters or linters
------------------------------------------

To temporarily skip a tool, use the `--skip` option for that tool. For example, run:

```bash
❯  pants --black-skip --flake8-skip lint ::
```

You can also use the `--lint-only` and `--fmt-only` options with the names of the tools:

```bash
❯ pants lint --only=black ::

# To run several, you can use either approach:
❯ pants fmt --only=black --only=isort ::
❯ pants fmt --only='["black", "isort"]' ::
```

You can also skip for certain targets with the `skip_<tool>` fields, which can be useful for [incrementally adopting new tools](https://www.youtube.com/watch?v=BOhcdRsmv0s). For example:

```python project/BUILD
python_sources(
    name="lib",
    # Skip Black for all non-test files in this folder.
    skip_black=True,
    overrides={
        "strutil.py": {"skip_flake8": True},
        ("docutil.py", "dirutil.py"): {"skip_isort": True},
    },
)

python_tests(
    name="tests",
    # Skip isort for all the test files in this folder.
    skip_isort=True,
)
```

When you run `pants fmt` and `pants lint`, Pants will ignore any files belonging to skipped targets.

Tip: only run over changed files
--------------------------------

With formatters and linters, there is usually no need to rerun on files that have not changed.

Use the option `--changed-since` to get much better performance, like this:

```bash
❯ pants --changed-since=HEAD fmt
```

or

```bash
❯ pants --changed-since=main lint
```

Pants will find which files have changed and only run over those files. See [Advanced target selection](doc:advanced-target-selection) for more information.

Tips for specific tools
-----------------------

### Order of `backend_packages` matters for `fmt`

Pants will run formatters in the order in which they appear in the `backend_packages` option.

For example, you likely want to put Autoflake (which removes unused imports) before Black and Isort, which will format your import statements.

```toml pants.toml
[GLOBAL]
backend_packages = [
    # Note that we want Autoflake to run before Black and isort,
    # so it must appear first.
    "pants.backend.python.experimental.autoflake",
    "pants.backend.python.black",
    "pants.backend.python.isort",
]
```

### Bandit, Flake8, and Pylint: report files

Flake8, Bandit, and Pylint can generate report files saved to disk.

For Pants to properly preserve the reports, instruct the tools to write to the `reports/` folder
by updating their config files, or `--flake8-args`, `--bandit-args`, and `--pylint-args`. For
example, in your `pants.toml`:

```toml
[bandit]
args = ["--output=reports/report.txt"]

[flake8]
args = ["--output-file=reports/report.txt"]

[pylint]
args = ["--output-format=text:reports/report.txt"]
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

### Black and isort: excluding files

In order to exclude files from being formatted by Black and isort, it may be necessary to tell those tools to respect skip configuration options. Otherwise, they may unconditionally format all files passed to them by the Pants runner.

Pants users report that this config works for them:

```toml
# pyproject.toml
[tool.isort]
# tell isort to respect skip_glob
filter_files = true  
# in particular, extend_skip_glob doesn't seem to work under Pants isort
skip_glob = [
    "**/*_skip_me.py",
    "**/*_skip_me.pyi",
]

[tool.black]
# in particular, extend-exclude and exclude will not work
force-exclude='''
^(
    .*_skip_me\.py(i)?
)$
'''
```
