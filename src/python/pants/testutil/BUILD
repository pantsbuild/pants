# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The `pantsbuild.pants.testutil` distribution is built as one version for all the various Python
# versions supported. However the build script used to build the `pantsbuild.pants` wheels runs for
# each separate Python version to produce version specific wheels, so we need to cancel the default
# interpreter constraints set by that process, using the `setup_py.python_requires` field, and also
# tagging the wheel for all the supported Python versions.
python_distribution(
    name="testutil_wheel",
    dependencies=[":testutil", ":pants_integration_test", ":rule_runner", ":py_typed"],
    wheel_config_settings={"--global-option": ["--python-tag", "py37.py38.py39"]},
    provides=setup_py(
        name="pantsbuild.pants.testutil",
        description="Test support for writing Pants plugins.",
        classifiers=["Topic :: Software Development :: Testing"],
        python_requires=">=3.7,<3.10",
    ),
)

python_sources(
    sources=["*.py", "!rule_runner.py", "!test_base.py", "!pants_integration_test.py", "!_test.py"],
)

python_sources(
    name="rule_runner",
    sources=["rule_runner.py", "test_base.py"],
    dependencies=["//BUILD_ROOT:files"],
)

python_sources(
    name="pants_integration_test",
    sources=["pants_integration_test.py"],
    dependencies=["//BUILD_ROOT:files", "src/python/pants/__main__.py"],
)

python_tests(name="tests", sources=["*_test.py", "!pants_integration_test.py"])

resource(name="py_typed", source="py.typed")
