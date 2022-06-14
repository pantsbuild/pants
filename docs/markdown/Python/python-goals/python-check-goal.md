---
title: "check"
slug: "python-check-goal"
excerpt: "How to use MyPy."
hidden: false
createdAt: "2020-06-30T15:53:37.799Z"
updatedAt: "2022-02-09T00:27:23.086Z"
---
[block:api-header]
{
  "title": "Activating MyPy"
}
[/block]
To opt-in, add `pants.backend.python.typecheck.mypy` to `backend_packages` in your config file. 
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.python\",\n  \"pants.backend.python.typecheck.mypy\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This will register a new `check` goal:

```bash
$ ./pants check helloworld/util/lang.py
$ ./pants check ::
```
[block:callout]
{
  "type": "success",
  "body": "MyPy determines which Python version to use based on its `python_version` option. If that's undefined, MyPy uses the interpreter the tool is run with. Because you can only use one config file at a time with MyPy, you cannot normally say to use `2.7` for part of your codebase but `3.6` for the rest; you must choose a single version.\n\nInstead, Pants will group your targets based on their [interpreter constraints](doc:python-interpreter-compatibility), and run all the Python 2 targets together and all the Python 3 targets together. It will automatically set `python_version` to the minimum compatible interpreter, such as a constraint like `[\"==2.7.*\", \">3.6\"]` using `2.7`.\n\nTo turn this off, you can still set `python_version` in `mypy.ini` or `--python-version`/`--py2` in `--mypy-args`; Pants will respect the value you set.",
  "title": "Benefit of Pants: typecheck Python 2-only and Python 3-only code at the same time"
}
[/block]
### Hook up a MyPy config file

Pants will automatically include your config file if it's located at `mypy.ini`, `.mypy.ini`, `setup.cfg`, or `pyproject.toml`.

Otherwise, you must set the option `[mypy].config` for Pants to include the config file in the process's sandbox and to instruct MyPy to load it.
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nconfig = \"build-support/mypy.ini\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### Change the MyPy version

Use the `version` option in the `[mypy]` scope:
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nversion = \"mypy==0.910\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
If you change this option, Pants's default lockfile for MyPy will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).

### Incrementally adopt MyPy with `skip_mypy=True`

You can tell Pants to skip running MyPy on certain files by adding `skip_mypy=True` to the relevant targets.
[block:code]
{
  "codes": [
    {
      "code": "# Skip MyPy for all the Python files in this directory\n# (both test and non-test files).\npython_sources(name=\"lib\", skip_mypy=True)\npython_tests(name=\"tests\", skip_mypy=True)\n\n# To only skip certain files, use the `overrides` field.\npython_sources(\n    name=\"lib\",\n    overrides={\n        \"util.py\": {\"skip_mypy\": True},\n        # Use a tuple to specify multiple files.\n        (\"user.py\", \"admin.py\"): {\"skip_mypy\": True},\n    },\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
When you run `./pants check ::`, Pants will skip any files belonging to skipped targets.
[block:callout]
{
  "type": "warning",
  "body": "The `skip_mypy` field only tells Pants not to provide the skipped files as direct input to MyPy. But MyPy, by default, will still try to check files that are [dependencies of the direct inputs](https://mypy.readthedocs.io/en/stable/running_mypy.html#following-imports).  So if your skipped files are dependencies of unskipped files, they may still be checked. \n\nTo change this behavior, use MyPy's [`--follow-imports` option](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-follow-imports), typically by setting it to `silent`. You can do so either by adding it to the [`args` option](https://www.pantsbuild.org/docs/reference-mypy#section-args) in the `[mypy]` section of your Pants config file, or by setting it in [`mypy.ini`](https://mypy.readthedocs.io/en/stable/config_file.html).",
  "title": "MyPy may still try to check the skipped files!"
}
[/block]
### First-party type stubs (`.pyi` files)

You can use [`.pyi` files](https://mypy.readthedocs.io/en/stable/stubs.html) for both first-party and third-party code. Include the `.pyi` files in the `sources` field for `python_source` / `python_sources` and `python_test` / `python_tests` targets. MyPy will use these stubs rather than looking at the implementation.

Pants's dependency inference knows to infer a dependency both on the implementation and the type stub. You can verify this by running `./pants dependencies path/to/file.py`.

When writing stubs for third-party libraries, you may need the set up the `[source].root_patterns` option so that [source roots](doc:source-roots) are properly stripped. For example:
[block:code]
{
  "codes": [
    {
      "code": "[source]\nroot_patterns = [\"mypy-stubs\", \"src/python\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "# Because we set `mypy-stubs` as a source root, this file will be \n# stripped to be simply `colors.pyi`. MyPy will look at this file for\n# imports of the `colors` module.\n\ndef red(s: str) -> str: ...",
      "language": "python",
      "name": "mypy-stubs/colors.pyi"
    },
    {
      "code": "python_sources(name=\"lib\")",
      "language": "python",
      "name": "mypy-stubs/BUILD"
    },
    {
      "code": "from colors import red\n\nif __name__ == \"__main__\":\n    print(red(\"I'm red!\"))",
      "language": "python",
      "name": "src/python/project/app.py"
    },
    {
      "code": "# Pants will infer a dependency both on the `ansicolors` requirement\n# and our type stub.\npython_sources(name=\"lib\")",
      "language": "python",
      "name": "src/python/project/BUILD"
    }
  ]
}
[/block]
### Third-party type stubs

You can install third-party type stubs (e.g. `types-requests`) like [normal Python requirements](doc:python-third-party-dependencies). Pants will infer a dependency on both the type stub and the actual dependency, e.g. both `types-requests` and `requests`, which you can confirm by running `./pants dependencies path/to/f.py`.

You can also install the type stub via the option `[mypy].extra_type_stubs`, which ensures the stubs are only used when running MyPy and are not included when, for example, [packaging a PEX](doc:python-package-goal).
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nextra_type_stubs = [\"types-requests==2.25.12\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### Add a third-party plugin

Add the plugin to the `extra_requirements` option in the `[mypy]` scope, then update your `mypy.ini` to load the plugin:
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nextra_requirements.add = [\"pydantic==1.6.1\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "[mypy]\nplugins =\n    pydantic.mypy",
      "language": "text",
      "name": "mypy.ini"
    }
  ]
}
[/block]
If you change this option, Pants's default lockfile for MyPy will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).

For some plugins, like `django-stubs`, you may need to always load certain source files, such as a `settings.py` file. You can make sure that this source file is always used by hijacking the `source_plugins` option, which allows you to specify targets whose `sources` should always be used when running MyPy. See the below section for more information about source plugins.

Some MyPy plugins also include type stubs, such as `django-stubs`. For type stubs to be used, the requirement must either be included in `[mypy].extra_type_stubs` or be loaded like a normal [third-party dependency](doc:python-third-party-dependencies), such as including in a `requirements.txt` file.

For example, to fully use the `django-stubs` plugin, your setup might look like this:
[block:code]
{
  "codes": [
    {
      "code": "[source]\nroot_patterns = [\"src/python\"]\n\n[mypy]\nextra_requirements = [\"django-stubs==1.5.0\"]\nextra_type_stubs = [\"django-stubs==1.5.0\"]\nsource_plugins = [\"src/python/project:django_settings\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "[mypy]\nplugins =\n    mypy_django_plugin.main\n\n[mypy.plugins.django-stubs]\ndjango_settings_module = project.django_settings",
      "language": "text",
      "name": "mypy.ini"
    },
    {
      "code": "from django.urls import URLPattern\n\nDEBUG = True\nDEFAULT_FROM_EMAIL = \"webmaster@example.com\"\nSECRET_KEY = \"not so secret\"\nMY_SETTING = URLPattern(pattern=\"foo\", callback=lambda: None)",
      "language": "python",
      "name": "src/python/project/django_settings.py"
    },
    {
      "code": "python_source(name=\"django_settings\", source=\"django_settings.py\")",
      "language": "python",
      "name": "src/python/project/BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "MyPy Protobuf support",
  "body": "Add `mypy_plugin = true` to the `[python-protobuf]` scope. See [Protobuf](doc:protobuf-python) for more information."
}
[/block]
### Add a first-party plugin

To add a [MyPy plugin](https://mypy.readthedocs.io/en/stable/extending_mypy.html) you wrote, add a `python_source` or `python_sources` target with the plugin's Python file(s) included in the `sources` field.

Then, add `plugins = path.to.module` to your MyPy config file, using the name of the module without source roots. For example, if your Python file is called `pants-plugins/mypy_plugins/custom_plugin.py`, and you set `pants-plugins` as a source root, then set `plugins = mypy_plugins.custom_plugin`. Set the `config` option in the `[mypy]` scope in your `pants.toml` to point to your MyPy config file.

Finally, set the option `source_plugins` in the `[mypy]` scope to include this target's address, e.g. `source_plugins = ["pants-plugins/mypy_plugins:plugin"]`. This will ensure that your plugin's sources are always included in the subprocess.

For example:
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nsource_plugins = [\"pants-plugins/mypy_plugins:plugin\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "plugins =\n    mypy_plugins.change_return_type",
      "language": "text",
      "name": "mypy.ini"
    },
    {
      "code": "python_source(name=\"plugin\", source=\"change_return_type.py\")",
      "language": "python",
      "name": "pants-plugins/mypy_plugins/BUILD"
    },
    {
      "code": "\"\"\"A contrived plugin that changes the return type of any \nfunction ending in `__overriden_by_plugin` to return None.\"\"\"\n\nfrom typing import Callable, Optional, Type\n\nfrom mypy.plugin import FunctionContext, Plugin\nfrom mypy.types import NoneType, Type as MyPyType\n\nfrom plugins.subdir.dep import is_overridable_function\n\nclass ChangeReturnTypePlugin(Plugin):\n    def get_function_hook(\n        self, fullname: str\n    ) -> Optional[Callable[[FunctionContext], MyPyType]]:\n        return hook if name.endswith(\"__overridden_by_plugin\") else None\n\n\ndef hook(ctx: FunctionContext) -> MyPyType:\n    return NoneType()\n\n\ndef plugin(_version: str) -> Type[Plugin]:\n    return ChangeReturnTypePlugin",
      "language": "python",
      "name": "pants-plugins/mypy_plugins/change_return_type.py"
    }
  ]
}
[/block]
Because this is a `python_source` or `python_sources` target, Pants will treat this code like your other Python files, such as running linters on it or allowing you to write a `python_distribution` target to distribute the plugin externally.

### Reports

MyPy can generate [various report files](https://mypy.readthedocs.io/en/stable/command_line.html#report-generation). 

For Pants to properly preserve the reports, instruct MyPy to write to the `reports/` folder by updating its config file or `--mypy-args`. For example, in your pants.toml:
[block:code]
{
  "codes": [
    {
      "code": "[mypy]\nargs = [\"--linecount-report=reports\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Pants will copy all reports into the folder `dist/check/mypy`.
[block:api-header]
{
  "title": "Known limitations"
}
[/block]
### Performance is often slower than normal

Pants does not yet leverage MyPy's caching mechanism and daemon, so a typical run with Pants will likely be slower than using MyPy directly.

We are [working to figure out](https://github.com/pantsbuild/pants/issues/10864) how to leverage MyPy's cache in a way that is safe and allows for things like remote execution.
[block:api-header]
{
  "title": "Tip: only run over changed files and their dependees"
}
[/block]
When changing type hints code, you not only need to run over the changed files, but also any code that depends on the changed files:

```bash
$ ./pants --changed-since=HEAD --changed-dependees=transitive check
```

See [Advanced target selection](doc:advanced-target-selection) for more information.