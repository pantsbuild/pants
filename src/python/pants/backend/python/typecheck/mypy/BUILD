# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lockfile", source="mypy.lock")

resource(name="older_lockfile_for_testing", source="older_mypy_for_testing.lock")

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
        "subsystem_test.py": {"timeout": 180},
        "rules_integration_test.py": {
            "dependencies": [":older_lockfile_for_testing"],
            "tags": ["platform_specific_behavior"],
            "timeout": 480,
        },
    },
)
