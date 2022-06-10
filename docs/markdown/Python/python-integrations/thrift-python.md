---
title: "Thrift"
slug: "thrift-python"
excerpt: "How to generate Python from Thrift."
hidden: false
createdAt: "2022-02-04T18:42:02.513Z"
updatedAt: "2022-03-05T00:21:17.402Z"
---
When your Python code imports Thrift generated files, Pants will detect the imports and run the Apache Thrift compiler to generate those files.
[block:callout]
{
  "type": "info",
  "title": "Example repository",
  "body": "See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Thrift to generate Python."
}
[/block]

[block:callout]
{
  "type": "success",
  "body": "With Pants, there's no need to manually regenerate your code or check it into version control. Pants will ensure you are always using up-to-date files in your builds.\n\nThanks to fine-grained caching, Pants will regenerate the minimum amount of code required when you do make changes.",
  "title": "Benefit of Pants: generated files are always up-to-date"
}
[/block]

[block:api-header]
{
  "title": "Step 1: Activate the Thrift Python backend"
}
[/block]
Add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.codegen.thrift.apache.python\",\n  \"pants.backend.python\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
You will also need to make sure that `thrift` is discoverable on your PATH, as Pants does not [install Thrift](https://thrift.apache.org/docs/install/) for you. Alternatively, you can tell Pants where to discover Thrift:
[block:code]
{
  "codes": [
    {
      "code": "[apache-thrift]\n# Defaults to the special string \"<PATH>\", which expands to your $PATH.\nthrift_search_paths = [\"/usr/bin\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This backend adds the new [`thrift_source`](doc:reference-thrift_source) target, which you can confirm by running `./pants help thrift_source`. 

To reduce boilerplate, you can also use the [`thrift_sources`](doc:reference-thrift_sources) target, which generates one `thrift_source` target per file in the `sources` field.
[block:code]
{
  "codes": [
    {
      "code": "thrift_sources(name=\"thrift\", sources=[\"user.thrift\", \"admin.thrift\"])\n\n# Spiritually equivalent to:\nthrift_source(name=\"user\", source=\"user.thrift\")\nthrift_source(name=\"admin\", source=\"admin.thrift\")\n\n# Thanks to the default `sources` value of '*.thrift', spiritually equivalent to:\nthrift_sources(name=\"thrift\")",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Step 2: Set up the `thrift` runtime library"
}
[/block]
Generated Python files require the [`thrift` dependency](https://pypi.org/project/thrift/) for their imports to work properly.

Add `thrift` to your project, e.g. your `requirements.txt` (see [Third-party dependencies](doc:python-third-party-dependencies)).
[block:code]
{
  "codes": [
    {
      "code": "thrift==0.15.0",
      "language": "text",
      "name": "requirements.txt"
    }
  ]
}
[/block]
Pants will then automatically add these dependencies to your `thrift_sources` targets created in the next step.
[block:api-header]
{
  "title": "Step 3: Generate `thrift_sources` target"
}
[/block]
Run [`./pants tailor`](doc:create-initial-build-files) for Pants to create a `thrift_sources` target wherever you have `.thrift` files:

```
$ ./pants tailor
Created src/thrift/BUILD:
  - Add thrift_sources target thrift
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.thrift` files, which you can confirm by running `./pants dependencies path/to/file.thrift`. You should also see the `python_requirement` target for the `thrift` library from the previous step.
[block:api-header]
{
  "title": "Step 4: Confirm Python imports are working"
}
[/block]
Now, you can import the generated Python modules in your Python code.

For each Thrift file, the compiler will generate at least three files `__init__.py`, `ttypes.py`, and `constants.py`. The location of those files—and corresponding imports—depends on whether you set `namespace py` in your `.thrift` file:
[block:parameters]
{
  "data": {
    "h-0": "`namespace py`",
    "0-0": "unset",
    "h-1": "Behavior",
    "h-2": "Example",
    "0-1": "Files generated as top-level modules, without any prefix directories.",
    "0-2": "`models/user.thrift`\n\nGenerated:\n- `__init__.py`\n- `user/__init__.py`\n- `user/constants.py`\n- `user/ttypes.py`\n\nPython import:\n`import user.ttypes`",
    "1-0": "set",
    "1-1": "Files generated into the namespace.",
    "1-2": "`models/user.thrift`, with `namespace py custom_namespace.user`\n\nGenerated:\n- `__init__.py`\n- `custom_namespace/__init__.py`\n- `custom_namespace/user/__init__.py`\n- `custom_namespace/user/constants.py`\n- `custom_namespace/user/ttypes.py`\n\nPython import:\n`import custom_namespace.user.ttypes`"
  },
  "cols": 3,
  "rows": 2
}
[/block]
As shown in the table, your Python imports depend on whether the Thrift file uses `namespace py`.

Imports behave the same regardless of whether you have [source roots](doc:source-roots), such as `src/thrift`. The import will still either be the top-level file like `user.ttypes` or the custom namespace.

Pants's dependency inference will detect Python imports of Thrift modules, which you can confirm by running `./pants dependencies path/to/file.py`.

You can also [manually add](doc:targets) the dependency:
[block:code]
{
  "codes": [
    {
      "code": "python_sources(dependencies=[\"models:models\"])",
      "language": "python",
      "name": "src/py/BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "TIp: set `namespace py`",
  "body": "Pants can handle Thrift regardless of whether you set `namespace py`. \n\nHowever, it's often a good idea to set the namespace because it can make your imports more predictable and declarative. It also reduces the risk of your Thrift file names conflicting with other Python modules used, such as those from third-party requirements.\n\nFor example, compare `import user.ttypes` to `import codegen.models.user.ttypes`."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Run `./pants export-codegen ::` to inspect the files",
  "body": "`./pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.\n\nYou do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants."
}
[/block]

[block:api-header]
{
  "title": "Multiple resolves"
}
[/block]
If you're using [multiple resolves](doc:python-third-party-dependencies) (i.e. multiple lockfiles), then you may need to set the `python_resolve` field. `thrift_source` targets only work with a single resolve, meaning, for example, that a `python_source` target that uses the resolve 'a' can only depend on Thrift targets that also uses this same resolve.

By default, `thrift_source` / `thrift_sources` targets use the resolve set by the option `[python].default_resolve`. To use a different resolve, set the field `python_resolve: str` to one of the values from the option `[python].resolves`.

You must also make sure that any resolves that use codegen include the `python_requirement` target for the `thrift` runtime library from Step 2. Pants will eagerly validate this for you.

For example:
[block:code]
{
  "codes": [
    {
      "code": "python_requirement(\n    name=\"thrift_resolve-a\",\n    requirements=[\"thrift==0.15.0\"],\n    resolve=\"resolve-a\",\n)\n\npython_requirement(\n    name=\"thrift_resolve-b\",\n    # Note that this version can be different than what we use \n    # above for `resolve-a`.\n    requirements=[\"thrift==0.13.0\"],\n    resolve=\"resolve-b\",\n)\n\nprotobuf_source(\n    name=\"data_science_models\",\n    source=\"data_science_models.thrift\",\n    resolve=\"resolve-a\",\n)\n\n\nprotobuf_source(\n    name=\"mobile_app_models\",\n    source=\"mobile_app_models.thrift\",\n    resolve=\"resolve-b\",\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
Pants 2.11 will be adding support for using the same `thrift_source` target with multiple resolves through a new `parametrize()` feature.