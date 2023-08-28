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
