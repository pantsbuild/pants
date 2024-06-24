# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    dependencies=[":resources"],
    overrides={
        # Enable `python -m pants ...` style execution ala `json.tool` or `venv`.
        "__main__.py": {"dependencies": ["src/python/pants/bin:pants_loader"]},
        "version.py": {"dependencies": ["src/python/pants/_version:resources"]},
    },
)

python_test_utils(name="test_utils")
python_tests(name="tests")

python_distribution(
    name="pants-packaged",
    dependencies=[
        "./__main__.py",
        ":resources",
        # Include the native client binary in the distribution.
        "src/python/pants/bin:native_client",
    ],
    # Because we have native code, this will cause the wheel to use whatever the ABI is for the
    # interpreter used to run setup.py, e.g. `cp39m-macosx_10_15_x86_64`.
    sdist=False,
    provides=setup_py(
        name="pantsbuild.pants",
        description="The ergonomic and hermetic software build system for Python, Java, Scala, "
        "Kotlin, Go, and Shell. Pants lets you fearlessly scale up your codebase.",
        # NB: by setting `ext_modules`, we signal to setup_py and bdist_wheel that this library
        # has native code. As a consequence, bdist_wheel pins the ABI (application binary interface)
        # used when creating the wheel, which is a good thing. We should be setting this ABI to ensure
        # consumers of pantsbuild.pants are using a compatible interpreter.
        # TODO(7344): the tuple syntax for ext_modules is deprecated. Use Extension once we support it.
        ext_modules=[("native_engine", {"sources": ["pants/dummy.c"]})],
        # N.B.: Must match [python] interpreter_constraints in pants.toml.
        python_requires="==3.9.*",
    ),
    entry_points={"console_scripts": {"pants": "pants.bin.pants_loader:main"}},
)

pex_binary(
    name="pants-pex",
    dependencies=[":pants-packaged"],
    script="pants",
    execution_mode="venv",
    shebang="/usr/bin/env python",
    strip_pex_env=False,
    layout="zipapp",
)

# NB: we use `dummy.c` to avoid clang/gcc complaining `error: no input files` when building
# `:pants-packaged`. We don't actually need to use any meaningful file here, though, because we
# use `entry_points` to link to the actual native code, so clang/gcc do not need to build any
# native code. This is just a dummy file.
resources(name="resources", sources=["py.typed", "dummy.c"])

PANTS_ARTIFACT_DEPENDENCIES = (
    "3rdparty/python#ansicolors",
    "3rdparty/python#chevron",
    "3rdparty/python#fasteners",
    "3rdparty/python#ijson",
    "3rdparty/python#node-semver",
    "3rdparty/python#packaging",
    "3rdparty/python#pex",
    "3rdparty/python#psutil",
    "3rdparty/python#python-lsp-jsonrpc",
    "3rdparty/python#PyYAML",
    "3rdparty/python#setproctitle",
    "3rdparty/python#setuptools",
    "3rdparty/python#toml",
    "3rdparty/python#types-PyYAML",
    "3rdparty/python#types-setuptools",
    "3rdparty/python#types-toml",
    "3rdparty/python#typing-extensions",
)

__dependencies_rules__(
    (
        # test modules should not depend on other test modules
        (python_tests, python_test),
        "!<python_tests>",
        "!<python_test>",
        "//BUILD_ROOT:files",
        "//pants.toml:files",
        "conftest.py",
        "pants/**",
        "pants-plugins/**",
        "tests/**",
        "testprojects/**",
        "<python_requirement>",
        "<python_requirements>",
        "?*",
    ),
    (
        # source modules can only depend on a restricted subset of 3rd-party requirements that
        # published Pants artifact will require; test modules do not have any restrictions and
        # can depend on any 3rd party requirement as they aren't included in the final artifact
        (
            {"type": python_sources},
            PANTS_ARTIFACT_DEPENDENCIES,
            "?//3rdparty/python#*",
            "*",
        )
    ),
    ("*", "*"),
)
