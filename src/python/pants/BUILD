# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        # Enable `python -m pants ...` style execution ala `json.tool` or `venv`.
        "__main__.py": {"dependencies": ["src/python/pants/bin:pants_loader"]},
        "version.py": {"dependencies": ["./VERSION:resources"]},
    },
)

python_test_utils(name="test_utils")

python_distribution(
    name="pants-packaged",
    dependencies=["./__main__.py", ":resources"],
    sdist=False,
    provides=setup_py(
        name="pantsbuild.pants",
        description="The ergonomic and hermetic software build system for Python, Java, Scala, "
        "Go, and Shell. Pants lets you fearlessly scale up your codebase.",
        # NB: by setting `ext_modules`, we signal to setup_py and bdist_wheel that this library
        # has native code. As a consequence, bdist_wheel pins the ABI (application binary interface)
        # used when creating the wheel, which is a good thing. We should be setting this ABI to ensure
        # consumers of pantsbuild.pants are using a compatible interpreter.
        # TODO(7344): the tuple syntax for ext_modules is deprecated. Use Extension once we support it.
        ext_modules=[("native_engine", {"sources": ["pants/dummy.c"]})],
    ),
    entry_points={"console_scripts": {"pants": "pants.bin.pants_loader:main}},
)

# NB: we use `dummy.c` to avoid clang/gcc complaining `error: no input files` when building
# `:pants-packaged`. We don't actually need to use any meaningful file here, though, because we
# use `entry_points` to link to the actual native code, so clang/gcc do not need to build any
# native code. This is just a dummy file.
resources(name="resources", sources=["VERSION", "py.typed", "dummy.c"])
