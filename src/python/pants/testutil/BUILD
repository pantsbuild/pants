# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The `pantsbuild.pants.testutil` distribution is built as one version for all the various Python
# versions supported. However the build script used to build the `pantsbuild.pants` wheels runs for
# each separate Python version to produce version specific wheels, so we need to cancel the default
# interpreter constraints set by that process, using the `setup_py.python_requires` field, and also
# tagging the wheel for all the supported Python versions.
python_distribution(
    name="testutil_wheel",
    dependencies=[":testutil", ":py_typed"],
    provides=setup_py(
        name="pantsbuild.pants.testutil",
        description="Test support for writing Pants plugins.",
        classifiers=["Topic :: Software Development :: Testing"],
        # N.B.: Must match [python] interpreter_constraints in pants.toml.
        python_requires="==3.9.*",
    ),
)

python_sources(
    sources=["*.py", "pants_integration_test.py", "!_test.py"],
    overrides={
        "pants_integration_test.py": {
            "dependencies": ["//BUILD_ROOT:files", "src/python/pants/__main__.py"]
        },
        "rule_runner.py": {"dependencies": ["//BUILD_ROOT:files"]},
    },
)

resource(name="py_typed", source="py.typed")
