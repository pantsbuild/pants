---
title: "Assets and archives"
slug: "assets"
excerpt: "How to include assets such as images and config files in your project."
hidden: false
createdAt: "2020-09-28T23:07:26.956Z"
updatedAt: "2022-01-29T16:32:14.551Z"
---
There are two ways to include asset files in your project: `resource` and `file` targets.
[block:api-header]
{
  "title": "`resources`"
}
[/block]
A [`resource`](doc:reference-resource) target is for files that are members of code packages, and are loaded via language-specific mechanisms, such as Python's `pkgutil.get_data()` or Java's `getResource()`.  

Pants will make resources available on the appropriate runtime path, such as Python's `PYTHONPATH` or the JVM classpath. Resources can be loaded directly from a binary in which they are embedded, such as a Pex file, without first unpacking it.

To reduce boilerplate, the [`resources`](doc:reference-resources) target generates a `resource` target per file in the `sources` field.

For example, to load resources in Python:
[block:code]
{
  "codes": [
    {
      "code": "import pkgutil\n\nif __name__ == \"__main__\":\n    config = pkgutil.get_data(\"project\", \"config.json\").decode(\"utf-8\")\n    print(f\"Config: {config}\")",
      "language": "python",
      "name": "src/python/project/app.py"
    },
    {
      "code": "python_source(\n  name=\"app\",\n  source=\"app.py\",\n  # Pants cannot infer this dependency, so we explicitly add it.\n  dependencies=[\":config\"],\n)\n\nresource(\n  name=\"config\",\n  source=\"config.json\",\n)",
      "language": "python",
      "name": "src/python/project/BUILD"
    },
    {
      "code": "{\"k1\": \"v\", \"k2\": \"v\"} ",
      "language": "json",
      "name": "src/python/project/config.json"
    }
  ]
}
[/block]
[Source root](doc:source-roots) stripping applies to resources, just as it does for code. In the example above, Python loads the resource named `project/config`, rather than `src/python/project/config.json`. 
[block:api-header]
{
  "title": "`files`"
}
[/block]
A `file` target is for loose files that are copied into the chroot where Pants runs your code. You can then load these files through direct mechanisms like Python's `open()` or Java's `FileInputStream`. The files are not associated with a code package, and must be extracted out of a deployed archive file before they can be loaded.

To reduce boilerplate, the [`files`](doc:reference-files) target generates a `file` target per file in the `sources` field.

For example, to load loose files in Python:
[block:code]
{
  "codes": [
    {
      "code": "def test_open_file():\n    with open(\"src/python/project/config.json\") as f:\n        content = f.read().decode()\n    assert content == '{\"k1\": \"v\", \"k2\": \"v\"}'",
      "language": "python",
      "name": "src/python/project/app_test.py"
    },
    {
      "code": "python_test(\n    name=\"app_test\",\n    source=\"app_test.py\",\n    # Pants cannot infer this dependency, so we explicitly add it.\n    dependencies=[\":config\"],\n)\n\nfile(\n    name=\"config\",\n    source=\"config.json\",\n)",
      "language": "python",
      "name": "src/python/project/BUILD"
    },
    {
      "code": "{\"k1\": \"v\", \"k2\": \"v\"} ",
      "language": "json",
      "name": "src/python/project/config.json"
    }
  ]
}
[/block]
Note that we open the file with its full path, including the `src/python` prefix.
[block:callout]
{
  "type": "warning",
  "title": "`file` targets are not included with binaries like `pex_binary`",
  "body": "Pants will not include dependencies on `file` / `files` targets when creating binaries like `pex_binary` and `python_awslambda` via `./pants package`. Filesystem APIs like Python's `open()` are relative to the current working directory, and they would try to read the files from where the binary is executed, rather than reading from the binary itself.\n\nInstead, use `resource` / `resources` targets or an `archive` target."
}
[/block]

[block:api-header]
{
  "title": "When to use each asset target type"
}
[/block]
### When to use `resource`

Use `resource` / `resources`  for files that are associated with (and typically live alongside) the code that loads them. That code's target (e.g. `python_source`) should depend on the `resource` target, ensuring that code and data together are embedded directly in a binary package, such as a wheel, Pex file or AWS Lambda.

### When to use `file`

Use `file` / `files` for files that aren't tightly coupled to any specific code, but need to be deployed alongside a binary, such as images served by a web server.

When writing tests, it is also often more convenient to open a file than to load a resource.
[block:parameters]
{
  "data": {
    "h-1": "`resource`",
    "h-2": "`file`",
    "0-0": "**Runtime path**",
    "0-1": "Relative to source root",
    "0-2": "Relative to repo root",
    "h-3": "`relocated_files`",
    "0-3": "Relocated, relative to repo root",
    "1-0": "**Loading mechanism**",
    "1-1": "Language's package loader, relative to package",
    "1-2": "Language's file loading idioms, relative to repo root",
    "2-0": "**Use with**",
    "2-1": "Targets that produce binaries, such as `pex_binary`, `python_distribution`, `python_awslambda`.",
    "2-2": "`archive` targets, tests"
  },
  "cols": 3,
  "rows": 3
}
[/block]

[block:api-header]
{
  "title": "`relocated_files`"
}
[/block]
When you use a `file` target, Pants will preserve the path to the files, relative to your build root. For example, the file `src/assets/logo.png` in your repo would be under this same path in the runtime chroot.

However, you may want to change the path to something else. For example, when creating an `archive` target and setting the `files` field, you might want those files to be placed at a different path in the archive; rather than `src/assets/logo.png`, for example, you might want the file to be at `imgs/logo.png`.

You can use the `relocated_files` target to change the path used at runtime for the files. Your other targets can then add this target to their `dependencies` field, rather than using the original `files` target:
[block:code]
{
  "codes": [
    {
      "code": "# Original file target.\nfile(\n    name=\"logo\",\n    source=\"logo.png\",\n)\n\n# At runtime, the file will be `imgs/logo.png`.\nrelocated_files(\n    name=\"relocated_logo\",\n    files_targets=[\":logo\"],\n    src=\"src/assets\",\n    dest=\"imgs\",\n)",
      "language": "python",
      "name": "src/assets/BUILD"
    }
  ]
}
[/block]
You can use an empty string in the `src` to add to an existing prefix and an empty string in the `dest` to strip an existing prefix.

If you want multiple different re-mappings for the same original files, you can define multiple `relocated_files` targets.

The `relocated_files` target only accepts `file` and `files` targets in its `files_targets` field. To relocate where other targets like `resource` and `python_source` show up at runtime, you need to change where that code is located in your repository.
[block:api-header]
{
  "title": "`archive`: create a `zip` or `tar` file"
}
[/block]
Running `./pants package` on an `archive` target will create a zip or tar file with built packages and/or loose files included. This is often useful when you want to create a binary and bundle it with some loose config files.

For example:
[block:code]
{
  "codes": [
    {
      "code": "archive(\n    name=\"app_with_config\",\n    packages=[\":app\"],\n    files=[\":production_config\"],\n    format=\"tar.xz\",\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
The format can be `zip`, `tar`, `tar.xz`, `tar.gz`, or `tar.bz2`.

The `packages` field is a list of targets that can be built using `./pants package`, such as `pex_binary`, `python_awslambda`, and even other `archive` targets. Pants will build the packages as if you had run `./pants package`. It will include the results in your archive using the same name they would normally have, but without the `dist/` prefix.

The `files` field is a list of `file`, `files`, and `relocated_files` targets. See [resources](doc:resources) for more details.

You can optionally set the field `output_path` to change the generated archive's name.