# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":config"])

python_tests(
    name="tests",
    overrides={
        "buildbarn_remote_cache_integration_test.py": {"timeout": 180},
        "buildbarn_remote_execution_integration_test.py": {"timeout": 300},
    },
)

resources(
    name="config",
    sources=["config/**/*"],
)
