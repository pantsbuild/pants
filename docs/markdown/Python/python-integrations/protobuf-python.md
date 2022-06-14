---
title: "Protobuf and gRPC"
slug: "protobuf-python"
excerpt: "How to generate Python from Protocol Buffers."
hidden: false
createdAt: "2020-05-05T16:51:05.928Z"
updatedAt: "2022-04-20T22:38:04.497Z"
---
When your Python code imports Protobuf generated files, Pants will detect the imports and run the Protoc compiler to generate those files.
[block:callout]
{
  "type": "info",
  "title": "Example repository",
  "body": "See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Protobuf to generate Python."
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
  "title": "Step 1: Activate the Protobuf Python backend"
}
[/block]
Add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.codegen.protobuf.python\",\n  \"pants.backend.python\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This adds the new [`protobuf_source`](doc:reference-protobuf_source) target, which you can confirm by running `./pants help protobuf_source`. 

To reduce boilerplate, you can also use the [`protobuf_sources`](doc:reference-protobuf_sources) target, which generates one `protobuf_source` target per file in the `sources` field.
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(name=\"protos\", sources=[\"user.proto\", \"admin.proto\"])\n\n# Spiritually equivalent to:\nprotobuf_source(name=\"user\", source=\"user.proto\")\nprotobuf_source(name=\"admin\", source=\"admin.proto\")\n\n# Thanks to the default `sources` value of '*.proto', spiritually equivalent to:\nprotobuf_sources(name=\"protos\")",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Enable the MyPy Protobuf plugin",
  "body": "The [MyPy Protobuf plugin](https://github.com/dropbox/mypy-protobuf) generates [`.pyi` type stubs](https://mypy.readthedocs.io/en/stable/stubs.html). If you use MyPy through Pants's [check goal](doc:python-check-goal), this will ensure MyPy understands your generated code.\n\nTo activate, set `mypy_plugin = true` in the `[python-protobuf]` scope:\n\n```toml\n[python-protobuf]\nmypy_plugin = true\n```\n\nMyPy will use the generated `.pyi` type stub file, rather than looking at the `.py` implementation file."
}
[/block]

[block:api-header]
{
  "title": "Step 2: Set up the `protobuf` and `grpcio` runtime libraries"
}
[/block]
Generated Python files require the [`protobuf` dependency](https://pypi.org/project/protobuf/) for their imports to work properly. If you're using gRPC, you also need the [`grpcio` dependency](https://pypi.org/project/grpcio/).

Add `protobuf`—and `grpcio`, if relevant— to your project, e.g. your `requirements.txt` (see [Third-party dependencies](doc:python-third-party-dependencies)).
[block:code]
{
  "codes": [
    {
      "code": "grpcio==1.32.0\nprotobuf>=3.12.1",
      "language": "text",
      "name": "requirements.txt"
    }
  ]
}
[/block]
Pants will then automatically add these dependencies to your `protobuf_source` targets created in the next step.
[block:api-header]
{
  "title": "Step 3: Generate `protobuf_sources` target"
}
[/block]
Run [`./pants tailor`](doc:create-initial-build-files) for Pants to create a `protobuf_sources` target wherever you have `.proto` files:

```
$ ./pants tailor
Created src/protos/BUILD:
  - Add protobuf_sources target protos
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.proto` files, which you can confirm by running `./pants dependencies path/to/file.proto`. You should also see the `python_requirement` target for the `protobuf` library from the previous step.

If you want gRPC code generated for all files in the folder, set `grpc=True`.
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(\n    name=\"protos\",\n    grpc=True,\n)",
      "language": "python",
      "name": "src/proto/example/BUILD"
    }
  ]
}
[/block]
If you only want gRPC generated for some files in the folder, you can use the `overrides` field:
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(\n    name=\"protos\",\n    overrides={\n        \"admin.proto\": {\"grpc\": True},\n        # You can also use a tuple for multiple files.\n        (\"user.proto\", \"org.proto\"): {\"grpc\": True},\n    },\n)",
      "language": "python",
      "name": "src/proto/example/BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Step 4: Confirm Python imports are working"
}
[/block]
Now, you can import the generated Python module in your Python code. For example, to import `project/example/f.proto`, add `import project.example.f_pb2` to your code. 

If you have [source roots](doc:source-roots) other than the repository root, remove the source root from the import. For example, `src/protos/example/f.proto` gets stripped to `import example.f_pb2`. See the below section on source roots for more info.

Pants's dependency inference will detect Python imports of Protobuf modules, which you can confirm by running `./pants dependencies path/to/file.py`.

If gRPC is activated, you can also import the module with `_pb2_grpc` at the end, e.g. `project.example.f_pb2_grpc`.

```python
from project.example.f_pb2 import HelloReply
from project.example.f_pb2_grcp import GreeterServicer
```
[block:callout]
{
  "type": "info",
  "title": "Run `./pants export-codegen ::` to inspect the files",
  "body": "`./pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.\n\nYou do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants."
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "You likely need to add empty `__init__.py` files",
  "body": "By default, Pants will generate the Python files in the same directory as the `.proto` file. To get Python imports working properly, you will likely need to add an empty `__init__.py` in the same location, and possibly in ancestor directories.\n\nSee the below section \"Protobuf and source roots\" for how to generate into a different directory. If you use this option, you will still likely need an empty `__init__.py` file in the destination directory."
}
[/block]

[block:api-header]
{
  "title": "Protobuf and source roots"
}
[/block]
By default, generated code goes into the same [source root](doc:source-roots) as the `.proto` file from which it was generated. For example, a file `src/proto/example/f.proto` will generate `src/proto/example/f_pb2.py`. 

However, this may not always be what you want. In particular, you may not want to have to add `__init__py` files under `src/proto` just so you can import Python code generated to that source root.

You can configure a different source root for generated code by setting the `python_source_root` field:
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(\n    name=\"protos\",\n    python_source_root='src/python'\n)",
      "language": "python",
      "name": "src/proto/example/BUILD"
    }
  ]
}
[/block]
Now `src/proto/example/f.proto` will generate `src/python/example/f_pb2.py`, i.e., the generated files will share a source root with your other Python code.
[block:callout]
{
  "type": "info",
  "title": "Set the `.proto` file's `package` relative to the source root",
  "body": "Remember that the `package` directive in your `.proto` file should be relative to the source root. \n\nFor example, if you have a file at `src/proto/example/subdir/f.proto`, you'd set its `package` to `example.subdir`; and in your Python code, `from example.subdir import f_pb2`."
}
[/block]

[block:api-header]
{
  "title": "Multiple resolves"
}
[/block]
If you're using [multiple resolves](doc:python-third-party-dependencies) (i.e. multiple lockfiles), then you may need to set the `python_resolve` field. `protobuf_source` targets only work with a single resolve, meaning, for example, that a `python_source` target that uses the resolve 'a' can only depend on Protobuf targets that also uses this same resolve.

By default, `protobuf_source` / `protobuf_sources` targets use the resolve set by the option `[python].default_resolve`. To use a different resolve, set the field `python_resolve: str` to one of the values from the option `[python].resolves`.

You must also make sure that any resolves that use codegen include `python_requirement` targets for the `protobuf` and `grpcio` runtime libraries from Step 2. Pants will eagerly validate this for you.

For example:
[block:code]
{
  "codes": [
    {
      "code": "python_requirement(\n    name=\"protobuf_resolve-a\",\n    requirements=[\"protobuf==3.19.4\"],\n    resolve=\"resolve-a\",\n)\n\npython_requirement(\n    name=\"protobuf_resolve-b\",\n    # Note that this version can be different than what we use \n    # above for `resolve-a`.\n    requirements=[\"protobuf==3.17.2\"],\n    resolve=\"resolve-b\",\n)\n\nprotobuf_source(\n    name=\"data_science_models\",\n    source=\"data_science_models.proto\",\n    resolve=\"resolve-a\",\n)\n\n\nprotobuf_source(\n    name=\"mobile_app_models\",\n    source=\"mobile_app_models.proto\",\n    resolve=\"resolve-b\",\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
Pants 2.11 will be adding support for using the same `protobuf_source` target with multiple resolves through a new `parametrize()` feature.