---
title: "PyOxidizer"
slug: "pyoxidizer"
excerpt: "Creating Python binaries through PyOxidizer."
hidden: false
createdAt: "2022-02-04T18:41:48.950Z"
updatedAt: "2022-02-28T23:26:51.526Z"
---
PyOxidizer allows you to distribute your code as a single binary file, similar to [Pex files](doc:pex-files). Unlike Pex, these binaries include a Python interpreter, often greatly simplifying distribution. 

See our blog post on [Packaging Python with the Pants PyOxidizer Plugin](https://blog.pantsbuild.org/packaging-python-with-the-pyoxidizer-pants-plugin/) for more discussion of the benefits of PyOxidizer.
[block:api-header]
{
  "title": "Step 1: Activate the backend"
}
[/block]
Add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.experimental.python.packaging.pyoxidizer\",\n  \"pants.backend.python\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This adds the new `pyoxidizer_binary` target, which you can confirm by running `./pants help pyoxidizer_binary`.
[block:callout]
{
  "type": "warning",
  "title": "This backend is experimental",
  "body": "We are still discovering the best ways to provide PyOxidizer support, such as how to make our [default template more useful](https://github.com/pantsbuild/pants/pull/14183/files#r788253973). This backend does not follow the normal [deprecation policy](doc:deprecation-policy), although we will do our best to minimize breaking changes.\n\nWe would [love your feedback](doc:getting-help) on this backend!"
}
[/block]

[block:api-header]
{
  "title": "Step 2: Define a `python_distribution` target"
}
[/block]
The `pyoxidizer_binary` target works by pointing to a `python_distribution` target with the code you want included. Pants then passes the distribution to PyOxidizer to install it as a binary. 

So, to get started, create a `python_distribution` target per [Building distributions](doc:python-distributions). 
[block:code]
{
  "codes": [
    {
      "code": "python_sources(name=\"lib\")\n\npython_distribution(\n    name=\"dist\",\n    dependencies=[\":lib\"],\n    provides=python_artifact(name=\"my-dist\", version=\"0.0.1\"),\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
The `python_distribution` must produce at least one wheel (`.whl`) file. If you are using Pants's default of `generate_setup=True`, make sure you also use Pants's default of `wheel=True`. Pants will eagerly error when building your `pyoxidizer_binary` if you use a `python_distribution` that does not produce wheels.
[block:api-header]
{
  "title": "Step 3: Define a `pyoxidizer_binary` target"
}
[/block]
Now, create a `pyoxidizer_binary` target and set the `dependencies` field to the [address](doc:targets) of the `python_distribution` you created previously.
[block:code]
{
  "codes": [
    {
      "code": "pyoxidizer_binary(\n    name=\"bin\",\n    dependencies=[\":dist\"],\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
Usually, you will want to set the `entry_point` field, which sets the behavior for what happens when you run the binary. 

If the `entry_point` field is not specified, running the binary will launch a Python interpreter with all the relevant code and dependencies loaded.

```bash
❯ ./dist/bin/x86_64-apple-darwin/release/install/bin
Python 3.9.7 (default, Oct 18 2021, 00:59:13) 
[Clang 13.0.0 ] on darwin
Type "help", "copyright", "credits" or "license" for more information.
>>> from myproject import myapp
>>> myapp.main()
Hello, world!
>>>
```

You can instead set `entry_point` to the Python module to execute (e.g. `myproject.myapp`). If specified, running the binary will launch the application similar to if it had been run as `python -m myproject.myapp`, for example.

```python
pyoxidizer_binary(
    name="bin",
    dependencies=[":dist"],
    entry_point="myproject.myapp",
)
```

```bash
❯ ./dist/bin/x86_64-apple-darwin/release/install/bin
Launching myproject.myapp from __main__
Hello, world!
```
[block:api-header]
{
  "title": "Step 4: Run `package`"
}
[/block]
Finally, run `./pants package` on your `pyoxidizer_binary` target to create a directory including your binary.

For example:

```
❯ ./pants package src/py/project:bin
14:15:31.18 [INFO] Completed: Building src.py.project:bin with PyOxidizer
14:15:31.23 [INFO] Wrote dist/src.py.project/bin/aarch64-apple-darwin/debug/install/bin
```

By default, Pants will write the package using this scheme: `dist/{path.to.tgt_dir}/{tgt_name}/{platform}/{debug,release}/install/{tgt_name}`. You can change the first part of this path by setting the `output_path` field, although you risk name collisions with other `pyoxidizer_binary` targets in your project. See [pyoxidizer_binary](doc:reference-pyoxidizer_binary) for more info.
[block:callout]
{
  "type": "warning",
  "title": "`debug` vs `release` builds",
  "body": "By default, PyOxidizer will build with Rust's \"debug\" mode, which results in much faster compile times but means that your binary will be slower to run. Instead, you can instruct PyOxidizer to build in [release mode](https://nnethercote.github.io/perf-book/build-configuration.html#release-builds) by adding this to `pants.toml`:\n\n```toml\n[pyoxidizer]\nargs = [\"--release\"]\n```\n\nOr by using the command line flag `./pants --pyoxidizer-args='--release' package path/to:tgt`."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "`run` support is upcoming",
  "body": "This will allow you to use `./pants run` to directly start your binary, without having to run from `dist/`. See https://github.com/pantsbuild/pants/pull/14646."
}
[/block]

[block:api-header]
{
  "title": "Advanced use cases"
}
[/block]

[block:callout]
{
  "type": "success",
  "title": "Missing functionality? Let us know!",
  "body": "We would like to keep improving Pants's PyOxidizer support. We encourage you to let us know what features are missing through [Slack or GitHub](doc:getting-help)!"
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "`[python-repos]` not yet supported for custom indexes",
  "body": "Currently, PyOxidizer can only resolve dependencies from PyPI and your first-party code. If you need support for custom indexes, please let us know by commenting on https://github.com/pantsbuild/pants/issues/14619. \n\n(We'd be happy to help mentor someone through this change, although please still comment either way!)"
}
[/block]
### `python_distribution`s that implicitly depend on each other

As explained at [Building distributions](doc:python-distributions#mapping-source-files-to-distributions), Pants automatically detects when one `python_distribution` depends on another, and it will add that dependency to the `install_requires` for the distribution. 

When this happens, PyOxidizer would naively try installing that first-party dependency from PyPI, which will likely fail. Instead, include all relevant `python_distribution` targets in the `dependencies` field of the `pyoxidizer_binary` target.
[block:code]
{
  "codes": [
    {
      "code": "python_sources(name=\"lib\")\n\npython_distribution(\n    name=\"dist\",\n    # Note that this python_distribution does not \n    # explicitly include project/utils:dist in its\n    # `dependencies` field, but Pants still \n    # detects an implicit dependency and will add \n    # it to this dist's `install_requires`.\n    dependencies=[\":lib\"],\n    provides=setup_py(name=\"main-dist\", version=\"0.0.1\"),\n)\n\npyoxidizer_binary(\n    name=\"bin\",\n    entry_point=\"hellotest.main\",\n    dependencies=[\":dist\", \"project/utils:dist\"],\n)",
      "language": "python",
      "name": "project/BUILD"
    },
    {
      "code": "from hellotest.utils.greeter import GREET\n\nprint(GREET)",
      "language": "python",
      "name": "project/main.py"
    },
    {
      "code": "GREET = 'Hello world!'",
      "language": "python",
      "name": "project/utils/greeter.py"
    },
    {
      "code": "python_sources(name=\"lib\")\n\npython_distribution(\n    name=\"dist\",\n    dependencies=[\":lib\"],\n    provides=setup_py(name=\"utils-dist\", version=\"0.0.1\"),\n)",
      "language": "python",
      "name": "project/utils/BUILD"
    }
  ]
}
[/block]
### `template` field

If the default PyOxidizer configuration that Pants generates is too limiting, a custom template can be used instead. Pants will expect a file with the extension `.bzlt` in a path relative to the `BUILD` file. 

```python
pyoxidizer_binary(
    name="bin",
    dependencies=[":dist"],
    entry_point="myproject.myapp",
    template="pyoxidizer.bzlt",
)
``` 

The custom `.bzlt` may use four parameters from within the Pants build process inside the template (these parameters must be prefixed by `$` or surrounded with `${ }` in the template). 

- `RUN_MODULE` - The re-formatted `entry_point` passed to this target (or None).
- `NAME` - This target's name.
- `WHEELS` - All python distributions passed to this target (or `[]`).
- `UNCLASSIFIED_RESOURCE_INSTALLATION` - This will populate a snippet of code to correctly inject the target's `filesystem_resources`.

For example, in a custom PyOxidizer configuration template, to use the `pyoxidizer_binary` target's `name` field:

```python
exe = dist.to_python_executable(
    name="$NAME",
    packaging_policy=policy,
    config=python_config,
)
```

You almost certainly will want to include this line, which is how the `dependencies` field gets consumed:

```python
exe.add_python_resources(exe.pip_install($WHEELS))
```

### `filesystem_resources` field

As explained in [PyOxidizer's documentation](https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_packaging_additional_files.html#installing-unclassified-files-on-the-filesystem), you may sometimes need to force certain dependencies to be installed to the filesystem. You can do that with the `filesystem_resources` field:

```python
pyoxidizer_binary(
    name="bin",
    dependencies=[":dist"],
    entry_point="myproject.myapp",
    filesystem_resources=["numpy==1.17"],
)
```