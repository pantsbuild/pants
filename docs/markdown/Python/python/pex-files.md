---
title: "Pex files"
slug: "pex-files"
hidden: false
createdAt: "2020-03-21T20:47:00.042Z"
updatedAt: "2022-02-09T01:33:52.341Z"
---
When working with Python code, Pants makes frequent use of the [Pex](https://github.com/pantsbuild/pex) (Python EXecutable) format. So, you'll see Pex referenced frequently in this documentation.

A Pex is a self-contained Python environment, similar in spirit to a virtualenv. A Pex can contain combinations of Python source files, 3rd-party requirements (sdists or wheels), resource files, and metadata describing the contents.

Importantly, this metadata can include:

- Python interpreter constraints.
- Python platforms, like `macosx_11_0_arm64-cp-39-cp39`.
- An entry point or console script.

A Pex can be bundled into a single `.pex` file. This file, when executed, knows how to unpack itself, find an interpreter that matches its constraints, and run itself on that interpreter. Therefore deploying code packaged in a Pex file is as simple as copying the file to an environment that has a suitable Python interpreter.

Check out [blog.pantsbuild.org/pants-pex-and-docker](https://blog.pantsbuild.org/pants-pex-and-docker/) for how this workflow gets even better when combined with Pants's Docker support!
