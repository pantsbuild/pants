# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    timeout=300,
    overrides={
        ("options_bootstrapper_test.py", "config_test.py"): {
            "dependencies": ["//BUILD_ROOT:files", "//pants.toml:files"],
        },
    },
)
