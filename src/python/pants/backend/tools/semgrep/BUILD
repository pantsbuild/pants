# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="lockfile", sources=["semgrep.lock*"])

python_sources(dependencies=[":lockfile"])

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "timeout": 240,
            "tags": ["platform_specific_behavior"],
        }
    },
)
