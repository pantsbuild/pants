# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        "pantsd_integration_test_base.py": {
            "dependencies": ["testprojects/src/python:coordinated_runs_directory"],
        }
    }
)

python_tests(
    name="tests",
    overrides={
        "process_manager_test.py": {
            "dependencies": [
                "//BUILD_ROOT:files",
            ],
        },
        "pants_daemon_core_test.py": {
            "dependencies": [
                "//BUILD_ROOT:files",
                "src/python/pants/bin:plugins",
            ]
        },
        "pantsd_integration_test.py": {
            "dependencies": [
                "testprojects/src/python:hello_directory",
                "testprojects/src/python:print_env_directory",
            ],
            "timeout": 2100,
        },
    },
)
