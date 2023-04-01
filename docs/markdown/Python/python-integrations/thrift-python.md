---
title: "Thrift"
slug: "thrift-python"
excerpt: "How to generate Python from Thrift."
hidden: false
createdAt: "2022-02-04T18:42:02.513Z"
---
When your Python code imports Thrift generated files, Pants will detect the imports and run the Apache Thrift compiler to generate those files.

> 📘 Example repository
> 
> See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Thrift to generate Python.

> 👍 Benefit of Pants: generated files are always up-to-date
> 
> With Pants, there's no need to manually regenerate your code or check it into version control. Pants will ensure you are always using up-to-date files in your builds.
> 
> Thanks to fine-grained caching, Pants will regenerate the minimum amount of code required when you do make changes.

Step 1: Activate the Thrift Python backend
------------------------------------------

Add this to your `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.codegen.thrift.apache.python",
  "pants.backend.python",
]
```

You will also need to make sure that `thrift` is discoverable on your PATH, as Pants does not [install Thrift](https://thrift.apache.org/docs/install/) for you. Alternatively, you can tell Pants where to discover Thrift:

```toml pants.toml
[apache-thrift]
# Defaults to the special string "<PATH>", which expands to your $PATH.
thrift_search_paths = ["/usr/bin"]
```

This backend adds the new [`thrift_source`](doc:reference-thrift_source) target, which you can confirm by running `pants help thrift_source`. 

To reduce boilerplate, you can also use the [`thrift_sources`](doc:reference-thrift_sources) target, which generates one `thrift_source` target per file in the `sources` field.

```python BUILD
thrift_sources(name="thrift", sources=["user.thrift", "admin.thrift"])

# Spiritually equivalent to:
thrift_source(name="user", source="user.thrift")
thrift_source(name="admin", source="admin.thrift")

# Thanks to the default `sources` value of '*.thrift', spiritually equivalent to:
thrift_sources(name="thrift")
```

Step 2: Set up the `thrift` runtime library
-------------------------------------------

Generated Python files require the [`thrift` dependency](https://pypi.org/project/thrift/) for their imports to work properly.

Add `thrift` to your project, e.g. your `requirements.txt` (see [Third-party dependencies](doc:python-third-party-dependencies)).

```text requirements.txt
thrift==0.15.0
```

Pants will then automatically add these dependencies to your `thrift_sources` targets created in the next step.

Step 3: Generate `thrift_sources` target
----------------------------------------

Run [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) for Pants to create a `thrift_sources` target wherever you have `.thrift` files:

```
$ pants tailor ::
Created src/thrift/BUILD:
  - Add thrift_sources target thrift
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.thrift` files, which you can confirm by running `pants dependencies path/to/file.thrift`. You should also see the `python_requirement` target for the `thrift` library from the previous step.

Step 4: Confirm Python imports are working
------------------------------------------

Now, you can import the generated Python modules in your Python code.

For each Thrift file, the compiler will generate at least three files `__init__.py`, `ttypes.py`, and `constants.py`. The location of those files—and corresponding imports—depends on whether you set `namespace py` in your `.thrift` file:

[block:parameters]
{
  "data": {
    "h-0": "`namespace py`",
    "h-1": "Behavior",
    "h-2": "Example",
    "0-0": "unset",
    "0-1": "Files generated as top-level modules, without any prefix directories.",
    "0-2": "`models/user.thrift`  \n  \nGenerated:  \n  \n- `__init__.py`\n- `user/__init__.py`\n- `user/constants.py`\n- `user/ttypes.py`Python import:  \n`import user.ttypes`",
    "1-0": "set",
    "1-1": "Files generated into the namespace.",
    "1-2": "`models/user.thrift`, with `namespace py custom_namespace.user`  \n  \nGenerated:  \n  \n- `__init__.py`\n- `custom_namespace/__init__.py`\n- `custom_namespace/user/__init__.py`\n- `custom_namespace/user/constants.py`\n- `custom_namespace/user/ttypes.py`Python import:  \n`import custom_namespace.user.ttypes`"
  },
  "cols": 3,
  "rows": 2,
  "align": [
    "left",
    "left",
    "left"
  ]
}
[/block]

As shown in the table, your Python imports depend on whether the Thrift file uses `namespace py`.

Imports behave the same regardless of whether you have [source roots](doc:source-roots), such as `src/thrift`. The import will still either be the top-level file like `user.ttypes` or the custom namespace.

Pants's dependency inference will detect Python imports of Thrift modules, which you can confirm by running `pants dependencies path/to/file.py`.

You can also [manually add](doc:targets) the dependency:

```python src/py/BUILD
python_sources(dependencies=["models:models"])
```

> 📘 TIp: set `namespace py`
> 
> Pants can handle Thrift regardless of whether you set `namespace py`. 
> 
> However, it's often a good idea to set the namespace because it can make your imports more predictable and declarative. It also reduces the risk of your Thrift file names conflicting with other Python modules used, such as those from third-party requirements.
> 
> For example, compare `import user.ttypes` to `import codegen.models.user.ttypes`.

> 📘 Run `pants export-codegen ::` to inspect the files
> 
> `pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.
> 
> You do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants.

Multiple resolves
-----------------

If you're using [multiple resolves](doc:python-third-party-dependencies) (i.e. multiple lockfiles), then you may need to set the `python_resolve` field. `thrift_source` targets only work with a single resolve, meaning, for example, that a `python_source` target that uses the resolve 'a' can only depend on Thrift targets that also uses this same resolve.

By default, `thrift_source` / `thrift_sources` targets use the resolve set by the option `[python].default_resolve`. To use a different resolve, set the field `python_resolve: str` to one of the values from the option `[python].resolves`.

You must also make sure that any resolves that use codegen include the `python_requirement` target for the `thrift` runtime library from Step 2. Pants will eagerly validate this for you.

If the same Thrift files should work with multiple resolves, you can use the
[`parametrize`](doc:targets#parametrizing-targets) mechanism.

For example:

```python BUILD
python_requirement(
    name="thrift-requirement",
    # Here, we use the same version of Thrift in both resolves. You could instead create
    # a distinct target per resolve so that they have different versions.
    requirements=["thrift==0.15.0""],
    resolve=parametrize("resolve-a", "resolve-b"),
)

thrift_sources(
    name="thrift",
    python_resolve=parametrize("resolve-a", "resolve-b")
)
```
