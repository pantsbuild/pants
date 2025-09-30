# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="lockfile", sources=["yamllint.lock*"])

python_sources(dependencies=[":lockfile"])

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "tags": ["platform_specific_behavior"],
        }
    },
)
