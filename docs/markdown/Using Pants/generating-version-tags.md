---
title: "Generating version tags from Git"
slug: "generating-version-tags"
hidden: false
---

Pants can generate a version string based on Git state that you can use during builds.

The `vcs_version` target
------------------------

To utilize this functionality, you first create a `vcs_version` target in some BUILD file:

```python src/BUILD
vcs_version(
    name="version",
    generate_to="src/version.py",
    template='version = {version}',
)
```

When you test, run or package any code that depends (directly or indirectly) on this target, 
Pants will compute a version string based on the current Git state, and then generate content 
using the specified `template` (with `{version}` serving as a placeholder for the version string)
at the path specified by `generate_to`.

Note that, similarly to how Pants handles other code generation tools (such as [Protobuf](doc:protobuf-python)), 
this content is not written out as a file into your source tree. Instead, the content is materialized
on the fly, as needed.  If you want to inspect the generated contents manually, you can use the
`export-codegen` goal:

```shell
./pants export-codegen src:version
```

Using the generated version
---------------------------

Code that depends on the `vcs_version` target can import and use the generated file:

```python src/util.py
from version import version
...
```

In this example we generated a Python source file, but you can generate code in any language, 
or even generate a text file for some code to load at runtime. 

In fact, in the Python case you don't even need an explicit dependency on the `vcs_version` target, as
one will be inferred from the import. This does not work (yet) for other languages, so those will
require an explicit dependency.

Note that because the implementation of this feature relies on a [Python library](https://github.com/pypa/setuptools_scm),
you will need to activate the [Pants Python backend](doc:/python-backend), even if you're not otherwise 
using Python in your repo.

The generated version string
----------------------------

Pants delegates the version string computation to [setuptools_scm](https://github.com/pypa/setuptools_scm).
See [here](https://github.com/pypa/setuptools_scm#default-versioning-scheme) for how it computes the version string from the Git state.

We don't yet support any of the configuration options that control how the string is computed. Please 
[let us know](doc:getting-help) if you need such advanced functionality.
