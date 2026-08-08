# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="test",
    overrides={
        "generate_github_workflows_test.py": {
            "dependencies": [
                "//pants.toml:files",
                "src/python/pants/backend/python/util_rules/pex_cli.py",
            ],
        },
    },
)
