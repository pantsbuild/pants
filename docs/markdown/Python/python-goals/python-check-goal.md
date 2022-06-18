---
title: "check"
slug: "python-check-goal"
excerpt: "How to use MyPy."
hidden: false
createdAt: "2020-06-30T15:53:37.799Z"
updatedAt: "2022-02-09T00:27:23.086Z"
---
Activating MyPy
---------------

To opt-in, add `pants.backend.python.typecheck.mypy` to `backend_packages` in your config file. 

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.python",
  "pants.backend.python.typecheck.mypy",
]
```

This will register a new `check` goal:

```bash
$ ./pants check helloworld/util/lang.py
$ ./pants check ::
```

> 👍 Benefit of Pants: typecheck Python 2-only and Python 3-only code at the same time
> 
> MyPy determines which Python version to use based on its `python_version` option. If that's undefined, MyPy uses the interpreter the tool is run with. Because you can only use one config file at a time with MyPy, you cannot normally say to use `2.7` for part of your codebase but `3.6` for the rest; you must choose a single version.
> 
> Instead, Pants will group your targets based on their [interpreter constraints](doc:python-interpreter-compatibility), and run all the Python 2 targets together and all the Python 3 targets together. It will automatically set `python_version` to the minimum compatible interpreter, such as a constraint like `["==2.7.*", ">3.6"]` using `2.7`.
> 
> To turn this off, you can still set `python_version` in `mypy.ini` or `--python-version`/`--py2` in `--mypy-args`; Pants will respect the value you set.

### Hook up a MyPy config file

Pants will automatically include your config file if it's located at `mypy.ini`, `.mypy.ini`, `setup.cfg`, or `pyproject.toml`.

Otherwise, you must set the option `[mypy].config` for Pants to include the config file in the process's sandbox and to instruct MyPy to load it.

```toml pants.toml
[mypy]
config = "build-support/mypy.ini"
```

### Change the MyPy version

Use the `version` option in the `[mypy]` scope:

```toml pants.toml
[mypy]
version = "mypy==0.910"
```

If you change this option, Pants's default lockfile for MyPy will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).

### Incrementally adopt MyPy with `skip_mypy=True`

You can tell Pants to skip running MyPy on certain files by adding `skip_mypy=True` to the relevant targets.

```python project/BUILD
# Skip MyPy for all the Python files in this directory
# (both test and non-test files).
python_sources(name="lib", skip_mypy=True)
python_tests(name="tests", skip_mypy=True)

# To only skip certain files, use the `overrides` field.
python_sources(
    name="lib",
    overrides={
        "util.py": {"skip_mypy": True},
        # Use a tuple to specify multiple files.
        ("user.py", "admin.py"): {"skip_mypy": True},
    },
)
```

When you run `./pants check ::`, Pants will skip any files belonging to skipped targets.

> 🚧 MyPy may still try to check the skipped files!
> 
> The `skip_mypy` field only tells Pants not to provide the skipped files as direct input to MyPy. But MyPy, by default, will still try to check files that are [dependencies of the direct inputs](https://mypy.readthedocs.io/en/stable/running_mypy.html#following-imports).  So if your skipped files are dependencies of unskipped files, they may still be checked. 
> 
> To change this behavior, use MyPy's [`--follow-imports` option](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-follow-imports), typically by setting it to `silent`. You can do so either by adding it to the [`args` option](https://www.pantsbuild.org/docs/reference-mypy#section-args) in the `[mypy]` section of your Pants config file, or by setting it in [`mypy.ini`](https://mypy.readthedocs.io/en/stable/config_file.html).

### First-party type stubs (`.pyi` files)

You can use [`.pyi` files](https://mypy.readthedocs.io/en/stable/stubs.html) for both first-party and third-party code. Include the `.pyi` files in the `sources` field for `python_source` / `python_sources` and `python_test` / `python_tests` targets. MyPy will use these stubs rather than looking at the implementation.

Pants's dependency inference knows to infer a dependency both on the implementation and the type stub. You can verify this by running `./pants dependencies path/to/file.py`.

When writing stubs for third-party libraries, you may need the set up the `[source].root_patterns` option so that [source roots](doc:source-roots) are properly stripped. For example:

```toml pants.toml
[source]
root_patterns = ["mypy-stubs", "src/python"]
```
```python mypy-stubs/colors.pyi
# Because we set `mypy-stubs` as a source root, this file will be 
# stripped to be simply `colors.pyi`. MyPy will look at this file for
# imports of the `colors` module.

def red(s: str) -> str: ...
```
```python mypy-stubs/BUILD
python_sources(name="lib")
```
```python src/python/project/app.py
from colors import red

if __name__ == "__main__":
    print(red("I'm red!"))
```
```python src/python/project/BUILD
# Pants will infer a dependency both on the `ansicolors` requirement
# and our type stub.
python_sources(name="lib")
```

### Third-party type stubs

You can install third-party type stubs (e.g. `types-requests`) like [normal Python requirements](doc:python-third-party-dependencies). Pants will infer a dependency on both the type stub and the actual dependency, e.g. both `types-requests` and `requests`, which you can confirm by running `./pants dependencies path/to/f.py`.

You can also install the type stub via the option `[mypy].extra_type_stubs`, which ensures the stubs are only used when running MyPy and are not included when, for example, [packaging a PEX](doc:python-package-goal).

```toml pants.toml
[mypy]
extra_type_stubs = ["types-requests==2.25.12"]
```

### Add a third-party plugin

Add the plugin to the `extra_requirements` option in the `[mypy]` scope, then update your `mypy.ini` to load the plugin:

```toml pants.toml
[mypy]
extra_requirements.add = ["pydantic==1.6.1"]
```
```text mypy.ini
[mypy]
plugins =
    pydantic.mypy
```

If you change this option, Pants's default lockfile for MyPy will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).

For some plugins, like `django-stubs`, you may need to always load certain source files, such as a `settings.py` file. You can make sure that this source file is always used by hijacking the `source_plugins` option, which allows you to specify targets whose `sources` should always be used when running MyPy. See the below section for more information about source plugins.

Some MyPy plugins also include type stubs, such as `django-stubs`. For type stubs to be used, the requirement must either be included in `[mypy].extra_type_stubs` or be loaded like a normal [third-party dependency](doc:python-third-party-dependencies), such as including in a `requirements.txt` file.

For example, to fully use the `django-stubs` plugin, your setup might look like this:

```toml pants.toml
[source]
root_patterns = ["src/python"]

[mypy]
extra_requirements = ["django-stubs==1.5.0"]
extra_type_stubs = ["django-stubs==1.5.0"]
source_plugins = ["src/python/project:django_settings"]
```
```text mypy.ini
[mypy]
plugins =
    mypy_django_plugin.main

[mypy.plugins.django-stubs]
django_settings_module = project.django_settings
```
```python src/python/project/django_settings.py
from django.urls import URLPattern

DEBUG = True
DEFAULT_FROM_EMAIL = "webmaster@example.com"
SECRET_KEY = "not so secret"
MY_SETTING = URLPattern(pattern="foo", callback=lambda: None)
```
```python src/python/project/BUILD
python_source(name="django_settings", source="django_settings.py")
```

> 📘 MyPy Protobuf support
> 
> Add `mypy_plugin = true` to the `[python-protobuf]` scope. See [Protobuf](doc:protobuf-python) for more information.

### Add a first-party plugin

To add a [MyPy plugin](https://mypy.readthedocs.io/en/stable/extending_mypy.html) you wrote, add a `python_source` or `python_sources` target with the plugin's Python file(s) included in the `sources` field.

Then, add `plugins = path.to.module` to your MyPy config file, using the name of the module without source roots. For example, if your Python file is called `pants-plugins/mypy_plugins/custom_plugin.py`, and you set `pants-plugins` as a source root, then set `plugins = mypy_plugins.custom_plugin`. Set the `config` option in the `[mypy]` scope in your `pants.toml` to point to your MyPy config file.

Finally, set the option `source_plugins` in the `[mypy]` scope to include this target's address, e.g. `source_plugins = ["pants-plugins/mypy_plugins:plugin"]`. This will ensure that your plugin's sources are always included in the subprocess.

For example:

```toml pants.toml
[mypy]
source_plugins = ["pants-plugins/mypy_plugins:plugin"]
```
```text mypy.ini
plugins =
    mypy_plugins.change_return_type
```
```python pants-plugins/mypy_plugins/BUILD
python_source(name="plugin", source="change_return_type.py")
```
```python pants-plugins/mypy_plugins/change_return_type.py
"""A contrived plugin that changes the return type of any 
function ending in `__overriden_by_plugin` to return None."""

from typing import Callable, Optional, Type

from mypy.plugin import FunctionContext, Plugin
from mypy.types import NoneType, Type as MyPyType

from plugins.subdir.dep import is_overridable_function

class ChangeReturnTypePlugin(Plugin):
    def get_function_hook(
        self, fullname: str
    ) -> Optional[Callable[[FunctionContext], MyPyType]]:
        return hook if name.endswith("__overridden_by_plugin") else None


def hook(ctx: FunctionContext) -> MyPyType:
    return NoneType()


def plugin(_version: str) -> Type[Plugin]:
    return ChangeReturnTypePlugin
```

Because this is a `python_source` or `python_sources` target, Pants will treat this code like your other Python files, such as running linters on it or allowing you to write a `python_distribution` target to distribute the plugin externally.

### Reports

MyPy can generate [various report files](https://mypy.readthedocs.io/en/stable/command_line.html#report-generation). 

For Pants to properly preserve the reports, instruct MyPy to write to the `reports/` folder by updating its config file or `--mypy-args`. For example, in your pants.toml:

```toml pants.toml
[mypy]
args = ["--linecount-report=reports"]
```

Pants will copy all reports into the folder `dist/check/mypy`.

Known limitations
-----------------

### Performance is often slower than normal

Pants does not yet leverage MyPy's caching mechanism and daemon, so a typical run with Pants will likely be slower than using MyPy directly.

We are [working to figure out](https://github.com/pantsbuild/pants/issues/10864) how to leverage MyPy's cache in a way that is safe and allows for things like remote execution.

Tip: only run over changed files and their dependees
----------------------------------------------------

When changing type hints code, you not only need to run over the changed files, but also any code that depends on the changed files:

```bash
$ ./pants --changed-since=HEAD --changed-dependees=transitive check
```

See [Advanced target selection](doc:advanced-target-selection) for more information.
