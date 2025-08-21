# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lockfile", source="mypy.lock")

resources(
    name="test_lockfiles",
    sources=[
        "older_mypy_for_testing.lock",
        "mypy_with_django_stubs.lock",
        "mypy_with_more_itertools.lock",
        "mypy_shadowing_tomli.lock",
        "mypy_py38.lock",
    ],
)

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfile"]}},
)

python_tests(
    name="tests",
    overrides={
        "mypyc_integration_test.py": {
            "dependencies": ["testprojects/src/python:mypyc_fib_directory"],
            "tags": ["platform_specific_behavior"],
            "timeout": 220,
        },
        "pep561_integration_test.py": {
            "runtime_package_dependencies": [
                "src/python/pants:pants-packaged",
                "src/python/pants/testutil:testutil_wheel",
            ],
            "timeout": 300,
        },
        "subsystem_test.py": {"timeout": 180},
        "rules_integration_test.py": {
            "dependencies": [":test_lockfiles"],
            "tags": ["platform_specific_behavior"],
            "timeout": 480,
        },
    },
)
