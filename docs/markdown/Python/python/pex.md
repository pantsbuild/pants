---
title: "Pex"
slug: "pex"
hidden: false
createdAt: "2020-03-21T20:47:00.042Z"
---
Pex files
---------
When working with Python code, Pants makes frequent use of the [Pex](https://github.com/pantsbuild/pex) (Python EXecutable) format. So, you'll see Pex referenced frequently in this documentation.

A Pex is a self-contained Python environment, similar in spirit to a virtualenv. A Pex can contain combinations of Python source files, 3rd-party requirements (sdists or wheels), resource files, and metadata describing the contents.

Importantly, this metadata can include:

- Python interpreter constraints.
- Python platforms, like `macosx_11_0_arm64-cp-39-cp39`.
- An entry point or console script.

A Pex can be bundled into a single `.pex` file. This file, when executed, knows how to unpack itself, find an interpreter that matches its constraints, and run itself on that interpreter. Therefore deploying code packaged in a Pex file is as simple as copying the file to an environment that has a suitable Python interpreter.

Check out [blog.pantsbuild.org/pants-pex-and-docker](https://blog.pantsbuild.org/pants-pex-and-docker/) for how this workflow gets even better when combined with Pants's Docker support!

Building a Pex
--------------

You define a Pex using the [`pex_binary`](doc:reference-pex_binary) target type:

```python path/to/mybinary/BUILD
python_sources(name="lib")

pex_binary(
    name="bin",
    dependencies=[":lib"],
    execution_mode="venv",
)
```

You then use the `package` goal to build the Pex, which will be output under the [dist/] directory.

```shell
$ pants package path/to/mybinary:bin
```

There are several fields you can set on a `pex_binary` to configure the layout, entry point and behavior of the resulting Pex.  See the [documentation](doc:reference-pex_binary) for details.


Setting the target platforms for a Pex
--------------------------------------

By default, the `package` goal builds a Pex that runs on the local machine's architecture and OS, and on a locally found interpreter compatible with your code's [interpreter constraints](doc:python-interpreter-compatibility). However, you can also build a multiplatform Pex - one that will run on multiple architecture+OS+interpreter combinations.

To do so, you must configure the [`complete_platforms`](doc:reference-pex_binary#codecomplete_platformscode) field on your `pex_binary` to point to `file` targets that provide detailed information about your target platforms. This is information that Pants can't determine itself because it's not running on those platforms:

```python BUILD
file(
    name="platform1",
    source="platform1.json",
)

file(
    name="platform2",
    source="platform2.json",
)

pex_binary(
    ...
    complete_platforms=[":platform1", ":platform2"]
    ...
)
```

You can generate the JSON content for these files by installing the [Pex](https://github.com/pantsbuild/pex) command-line tool on the target platform and running `pex3 interpreter inspect --markers --tags` against the appropriate interpreter. You can run `pex3 interpreter inspect --help` for more options, and in particular for how to select the desired target interpreter.

> 🚧 Platform-specific dependencies must be available as wheels
>
> Pants can't cross-compile platform-specific sdists for the target platforms. All platform-specific third-party packages that your Pex transitively depends on must be available as prebuilt wheels for each platform you care about. If those wheels aren't available on PyPI you can always build them manually once and host them on a private package repository.

Setting Pex and Pip versions
----------------------------

Pants makes use of the [Pex](https://github.com/pantsbuild/pex) command-line tool internally for Pex building. The Pex version that Pants uses is specified by the `version` option under the `pex-cli` subsystem. The known Pex versions are specified by the `known_versions` option under the `pex-cli` subsystem. You can see all Pex tool options and their current values by running `pants help-advanced pex-cli`. To upgrade the Pex version, update these option values accordingly. For instance, in `pants.toml`, to upgrade to Pex 2.1.143:

```[pex-cli]
version = "v2.1.143"
known_versions = [
  "v2.1.143|macos_arm64|7dba8776000b4f75bc9af850cb65b2dc7720ea211733e8cb5243c0b210ef3c19|4194291",
  "v2.1.143|macos_x86_64|7dba8776000b4f75bc9af850cb65b2dc7720ea211733e8cb5243c0b210ef3c19|4194291",
  "v2.1.143|linux_x86_64|7dba8776000b4f75bc9af850cb65b2dc7720ea211733e8cb5243c0b210ef3c19|4194291",
  "v2.1.143|linux_arm64|7dba8776000b4f75bc9af850cb65b2dc7720ea211733e8cb5243c0b210ef3c19|4194291"
]
```

The Pex version determines which Pip versions are supported. To see the lists of Pip versions a certain version of Pex supports you can either install that version of Pex as a standalone CLI and run `pex --help`, or examine [pex/pip/version.py](https://github.com/pantsbuild/pex/blob/main/pex/pip/version.py) in the sources of the relevant Pex version. 

The Pip version that Pex uses is determined by the `pip_version` option in Pants. To upgrade the Pip version, update this option value accordingly. For instance, in `pants.toml`, to set the Pip version to be the latest supported by Pex:

```[python]
pip_version = "latest"
```
