# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(
    name="lockfiles",
    sources=[
        "black.lock",
        # Lockfile for the version of Black Pants used to provide (with the '23 stable style), to
        # make upgrading easier
        "black-23.12.lock",
    ],
)

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfiles"]}},
)

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "tags": ["platform_specific_behavior"],
            "timeout": 240,
        }
    },
)
