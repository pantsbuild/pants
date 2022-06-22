---
title: "Interpreter compatibility"
slug: "python-interpreter-compatibility"
excerpt: "How to configure which Python version(s) your project should use."
hidden: false
createdAt: "2020-04-30T20:06:44.249Z"
updatedAt: "2022-04-23T21:58:23.364Z"
---
Setting the default Python version
----------------------------------

Configure your default Python interpreter compatibility constraints in `pants.toml` like this:

```toml pants.toml
[python]
interpreter_constraints = ["CPython==3.8.*"]
```

The value can be any valid Requirement-style strings. You can use multiple strings to OR constraints, and use commas within each string to AND constraints. For example:

| Constraint                           | What it means                            |
| :----------------------------------- | :--------------------------------------- |
| `['CPython>=3.6,<4']`                | CPython 3.6+, but not CPython 4 or later |
| `['CPython==3.7.3']`                 | CPython 3.7.3                            |
| `['PyPy']`                           | any version of PyPy                      |
| `['CPython==2.7.*', 'CPython>=3.5']` | CPython 2.7 or 3.5+                      |

As a shortcut, you can leave off `CPython` and just put the version specifier. For example, `==3.8` will be expanded automatically to `CPython==3.8`.

Using multiple Python versions in the same project
--------------------------------------------------

Pants also allows you to specify the interpreter compatibility for particular targets. This allows you to use multiple Python versions in the same repository, such as allowing you to incrementally migrate from Python 2 to Python 3.

Use the `interpreter_constraints` field on a Python target, like this:

```python BUILD
python_sources(
    name="python2_target",
    interpreter_constraints=["==2.7.*"],
)
```

If `interpreter_constraints` is left off, the target will default to the value from the option `interpreter_constraints` in `[python]`.

To only change the interpreter constraints for a few files, you can use the `overrides` field:

```python BUILD
python_sources(
    name="lib",
    overrides={
        "py2.py": {"interpreter_constraints": ["==2.7.*"]},
        # You can use a tuple for multiple files:
        ("common.py", "f.py"): {"interpreter_constraints": ["==2.7.*"]},
)
```

Pants will merge the constraints from the target's _transitive closure_ when deciding which interpreter to use, meaning that it will look at the constraints of the target, its dependencies, and the dependencies of those dependencies. For example:

- Target A sets `interpreter_constraints==['2.7.*']`.
- Target B sets `interpreter_contraints=['>=3.5']`, and it depends on Target A.
- When running `./pants package :b`, Pants will merge the constraints to `['==2.7.*,>=3.5']`. This is impossible to satisfy, so Pants will error.

This means that every dependency of a target must also be compatible with its interpreter constraints. Generally, you will want to be careful that your common `python_source` / `python_sources` targets are compatible with multiple Python versions because they may be depended upon by other targets. Meanwhile, `pex_binary` and `python_test` / `python_tests` targets can have specific constraints because they are (conventionally) never dependencies for other targets. For example:

```python
python_sources(
    # Source files are compatible with Python 2.7 or 3.5+.
    interpreter_constraints=["==2.7.*", ">=3.5"]`,
)

pex_binary(
    name="binary",
    entry_point="app.py",
    # When merged with the python_sources's constraints, the final result will 
    # require `>=3.5`.
    interpreter_constraints=[">=3.5"],
)
```

> 🚧 Pants cannot validate that your interpreter constraints are accurate
> 
> Pants accepts your interpreter constraints at face value. If you use a constraint like `'>=3.6'`, Pants will trust you that your code indeed works with any interpreter >= 3.6, as Pants has no way to audit if your code is actually compatible.
> 
> Instead, consider running your unit tests with every Python version you claim to support to ensure that your code really is compatible:
> 
> ```python
> python_test(
>    source="util_test.py",
>    interpreter_constraints=parametrize(py2=["==2.7.*"], py3=["==3.6.*"]),
> )
> ```

### Tip: activate `pants.backend.python.mixed_interpreter_constraints`

We recommend adding `pants.backend.python.mixed_interpreter_constraints` to `backend_packages` in the `[GLOBAL]` scope, which will add the new goal `py-constraints`.

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.python",
  "pants.backend.python.mixed_interpreter_constraints",
]
```

You can run `./pants py-constraints $file/$target` to see what final interpreter constraints will be used, and why. For example:

```
$ ./pants py-constraints helloworld/main.py
Final merged constraints: CPython==2.7.*,>=3.5 OR CPython>=3.5

CPython>=3.5
    helloworld/main.py

CPython==2.7.* OR CPython>=3.5
    helloworld/util/__init__.py
    helloworld/util/config_loader.py
    helloworld/util/lang.py
    helloworld/util/proto/__init__.py:init
    helloworld/util/proto/config.proto
```

#### `py-constraints --summary`

You can run `./pants py-constraints --summary` for Pants to generate a CSV giving an overview of your project's interpreter constraints:

[block:image]
{
  "images": [
    {
      "image": [
        "https://files.readme.io/8ebc968-Screen_Shot_2020-11-12_at_9.19.56_AM.png",
        "Screen Shot 2020-11-12 at 9.19.56 AM.png"
      ],
      "caption": "Result of `./pants py-constraints --summary`, then importing the CSV into Google Sheets."
    }
  ]
}
[/block]

We recommend then importing this CSV into a tool like Pandas or Excel to filter/sort the data.

The `# Dependees` column is useful to see how impactful it is to port a file, and the `# Dependencies` can be useful to see how easy it would be to port.

> 📘 Tips for Python 2 -> Python 3 migrations
> 
> While every project will have different needs and scope, there are a few best practices with Pants that will allow for a more successful migration.
> 
> - Start by setting the `interpreter_constraints` option in `[python]` to describe the status of the majority of your targets. If most are only compatible with Python 2, set it to `['==2.7.*']`. If most are compatible with Python 2 _and_ Python 3, set to `['==2.7', '>=3.5']`. If most are only compatible with Python 3, set to `[>=3.5]`. For any targets that don't match these global constraints, override with the `interpreter_constraints` field.
> - Run `./pants py-constraints --summary` and sort by `# Dependees` from Z to A to find your most-used files. Focus on getting these targets to be compatible with Python 2 and 3. You may want to also sub-sort the CSV by `# Dependencies` to find what is easiest to port.
> - Once >40% of your targets work with both Python 2 and Python 3, change the `interpreter_constraints` option in `[python]` to specify compatibility with both Python 2.7 and Python 3 so that all new code uses this by default.
> - For files with no or few dependencies, change them to Python 3-only when possible so that you can start using all the neat new Python 3 features like f-strings! Use the CSV from `./pants py-constraints --summary` to find these. You can also do this if every "dependee" target works exclusively with Python 3, which you can find by the `Transitive Constraints` column and by running `./pants py-constraints path/to/file.py`.
> 
> Check out [this blog post](https://enterprise.foursquare.com/intersections/article/how-our-intern-led-pants-migration-to-python-3/) on Pants' own migration to Python 3 in 2019 for more general tips on Python 3 migrations.

Changing the interpreter search path
------------------------------------

Pants will default to looking at your `$PATH` to discover Python interpreters. You can change this by setting the option `search_paths` in the `[python-bootstrap]` scope.

You can specify absolute paths to interpreter binaries and/or to directories containing interpreter binaries. In addition, Pants understands some special symbols:

- `<PATH>`: read the `$PATH` env var
- `<PYENV>`: use all directories in `$(pyenv root)/versions`
- `<PYENV_LOCAL>`: the interpreter specified in the local file `.python-version`
- `<ASDF>`, all Python versions currently configured by ASDF, with a fallback to all installed versions.
- `<ASDF_LOCAL>`, the ASDF interpreter with the version in `<BUILD_ROOT>/.tool-versions`.

For example:

```toml pants.toml
[python-bootstrap]
search_path = ["<PYENV>", "/opt/python3"]
```
