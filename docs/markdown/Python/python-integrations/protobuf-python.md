---
title: "Protobuf and gRPC"
slug: "protobuf-python"
excerpt: "How to generate Python from Protocol Buffers."
hidden: false
createdAt: "2020-05-05T16:51:05.928Z"
---
When your Python code imports Protobuf generated files, Pants will detect the imports and run the Protoc compiler to generate those files.

> 📘 Example repository
> 
> See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Protobuf to generate Python.

> 👍 Benefit of Pants: generated files are always up-to-date
> 
> With Pants, there's no need to manually regenerate your code or check it into version control. Pants will ensure you are always using up-to-date files in your builds.
> 
> Thanks to fine-grained caching, Pants will regenerate the minimum amount of code required when you do make changes.

Step 1: Activate the Protobuf Python backend
--------------------------------------------

Add this to your `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.codegen.protobuf.python",
  "pants.backend.python",
]
```

This adds the new [`protobuf_source`](doc:reference-protobuf_source) target, which you can confirm by running `pants help protobuf_source`. 

To reduce boilerplate, you can also use the [`protobuf_sources`](doc:reference-protobuf_sources) target, which generates one `protobuf_source` target per file in the `sources` field.

```python BUILD
protobuf_sources(name="protos", sources=["user.proto", "admin.proto"])

# Spiritually equivalent to:
protobuf_source(name="user", source="user.proto")
protobuf_source(name="admin", source="admin.proto")

# Thanks to the default `sources` value of '*.proto', spiritually equivalent to:
protobuf_sources(name="protos")
```

> 📘 Enable the MyPy Protobuf plugin
> 
> The [MyPy Protobuf plugin](https://github.com/dropbox/mypy-protobuf) generates [`.pyi` type stubs](https://mypy.readthedocs.io/en/stable/stubs.html). If you use MyPy through Pants's [check goal](doc:python-check-goal), this will ensure MyPy understands your generated code.
> 
> To activate, set `mypy_plugin = true` in the `[python-protobuf]` scope:
> 
> ```toml
> [python-protobuf]
> mypy_plugin = true
> ```
> 
> MyPy will use the generated `.pyi` type stub file, rather than looking at the `.py` implementation file.

Step 2: Set up the `protobuf` and `grpcio` runtime libraries
------------------------------------------------------------

Generated Python files require the [`protobuf` dependency](https://pypi.org/project/protobuf/) for their imports to work properly. If you're using gRPC, you also need the [`grpcio` dependency](https://pypi.org/project/grpcio/).

Add `protobuf`—and `grpcio`, if relevant— to your project, e.g. your `requirements.txt` (see [Third-party dependencies](doc:python-third-party-dependencies)).

```text requirements.txt
grpcio==1.32.0
protobuf>=3.12.1
```

Pants will then automatically add these dependencies to your `protobuf_source` targets created in the next step.

Step 3: Generate `protobuf_sources` target
------------------------------------------

Run [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) for Pants to create a `protobuf_sources` target wherever you have `.proto` files:

```
$ pants tailor ::
Created src/protos/BUILD:
  - Add protobuf_sources target protos
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.proto` files, which you can confirm by running `pants dependencies path/to/file.proto`. You should also see the `python_requirement` target for the `protobuf` library from the previous step.

If you want gRPC code generated for all files in the folder, set `grpc=True`.

```python src/proto/example/BUILD
protobuf_sources(
    name="protos",
    grpc=True,
)
```

If you only want gRPC generated for some files in the folder, you can use the `overrides` field:

```python src/proto/example/BUILD
protobuf_sources(
    name="protos",
    overrides={
        "admin.proto": {"grpc": True},
        # You can also use a tuple for multiple files.
        ("user.proto", "org.proto"): {"grpc": True},
    },
)
```

Step 4: Confirm Python imports are working
------------------------------------------

Now, you can import the generated Python module in your Python code. For example, to import `project/example/f.proto`, add `import project.example.f_pb2` to your code. 

If you have [source roots](doc:source-roots) other than the repository root, remove the source root from the import. For example, `src/protos/example/f.proto` gets stripped to `import example.f_pb2`. See the below section on source roots for more info.

Pants's dependency inference will detect Python imports of Protobuf modules, which you can confirm by running `pants dependencies path/to/file.py`.

If gRPC is activated, you can also import the module with `_pb2_grpc` at the end, e.g. `project.example.f_pb2_grpc`.

```python
from project.example.f_pb2 import HelloReply
from project.example.f_pb2_grcp import GreeterServicer
```

> 📘 Run `pants export-codegen ::` to inspect the files
> 
> `pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.
> 
> You do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants.

> 🚧 You likely need to add empty `__init__.py` files
> 
> By default, Pants will generate the Python files in the same directory as the `.proto` file. To get Python imports working properly, you will likely need to add an empty `__init__.py` in the same location, and possibly in ancestor directories.
> 
> See the below section "Protobuf and source roots" for how to generate into a different directory. If you use this option, you will still likely need an empty `__init__.py` file in the destination directory.

Protobuf and source roots
-------------------------

By default, generated code goes into the same [source root](doc:source-roots) as the `.proto` file from which it was generated. For example, a file `src/proto/example/f.proto` will generate `src/proto/example/f_pb2.py`. 

However, this may not always be what you want. In particular, you may not want to have to add `__init__py` files under `src/proto` just so you can import Python code generated to that source root.

You can configure a different source root for generated code by setting the `python_source_root` field:

```python src/proto/example/BUILD
protobuf_sources(
    name="protos",
    python_source_root='src/python'
)
```

Now `src/proto/example/f.proto` will generate `src/python/example/f_pb2.py`, i.e., the generated files will share a source root with your other Python code.

> 📘 Set the `.proto` file's `package` relative to the source root
> 
> Remember that the `package` directive in your `.proto` file should be relative to the source root. 
> 
> For example, if you have a file at `src/proto/example/subdir/f.proto`, you'd set its `package` to `example.subdir`; and in your Python code, `from example.subdir import f_pb2`.

Multiple resolves
-----------------

If you're using [multiple resolves](doc:python-third-party-dependencies) (i.e. multiple lockfiles), then you may need to set the `python_resolve` field. `protobuf_source` targets only work with a single resolve, meaning, for example, that a `python_source` target that uses the resolve 'a' can only depend on Protobuf targets that also uses this same resolve.

By default, `protobuf_source` / `protobuf_sources` targets use the resolve set by the option `[python].default_resolve`. To use a different resolve, set the field `python_resolve: str` to one of the values from the option `[python].resolves`.

You must also make sure that any resolves that use codegen include `python_requirement` targets for the `protobuf` and `grpcio` runtime libraries from Step 2. Pants will eagerly validate this for you.

If the same Protobuf files should work with multiple resolves, you can use the
[`parametrize`](doc:targets#parametrizing-targets) mechanism.

For example:

```python BUILD
python_requirement(
    name="protobuf",
    # Here, we use the same version of Protobuf in both resolves. You could instead create
    # a distinct target per resolve so that they have different versions.
    requirements=["protobuf==3.19.4"],
    resolve=parametrize("resolve-a", "resolve-b"),
)

protobuf_sources(
    name="protos",
    python_resolve=parametrize("resolve-a", "resolve-b")
)
```

Buf: format and lint Protobuf
-----------------------------

Pants integrates with the [`Buf`](https://buf.build/blog/introducing-buf-format) formatter and linter for Protobuf files.

To activate, add this to `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.codegen.protobuf.lint.buf",
]
```

Now you can run `pants fmt` and `pants lint`:

```
❯ pants lint src/protos/user.proto
```

Use `pants fmt lint dir:` to run on all files in the directory, and `pants fmt lint dir::` to run on all files in the directory and subdirectories.

Temporarily disable Buf with `--buf-fmt-skip` and `--buf-lint-skip`:

```bash
❯ pants --buf-fmt-skip fmt ::
```

Only run Buf with `--lint-only=buf-fmt` or `--lint-only=buf-lint`, and `--fmt-only=buf-fmt`:

```bash
❯ pants fmt --only=buf-fmt ::
```
