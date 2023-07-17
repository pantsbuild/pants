# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="resources", sources=["versions_info.json"])
python_sources(overrides={"rules.py": {"dependencies": [":resources"]}})
python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "timeout": 300,
        }
    },
)
