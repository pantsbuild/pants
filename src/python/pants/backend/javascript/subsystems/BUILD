# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        "nodejs_test.py": {"timeout": 240},
        "nodejs_tool_test.py": {"timeout": 120, "dependencies": [":cowsay_lockfiles"]},
    },
)

resources(name="cowsay_lockfiles", sources=["package-lock.json", "pnpm-lock.yaml", "yarn.lock"])
