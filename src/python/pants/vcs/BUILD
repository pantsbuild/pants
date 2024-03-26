# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        "changed_integration_test.py": {
            "timeout": 350,
            "dependencies": ["testprojects/pants-plugins/src/python/python_constant/register.py"],
        },
        "git_test.py": {"timeout": 120},
    },
)
