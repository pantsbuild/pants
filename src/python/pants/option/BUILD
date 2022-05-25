# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        (
            "config_test.py",
            "options_test.py",
            "options_bootstrapper_test.py",
            "subsystem_test.py",
        ): {
            "dependencies": ["//BUILD_ROOT:files", "//pants.toml:files"],
        },
        "global_options_test.py": {
            "dependencies": [
                "//BUILD_ROOT:files",
                "//pants.toml:files",
                # This test loads `pants.toml`, which references many of these plugins.
                "src/python/pants/bin:plugins",
            ],
        },
        "options_integration_test.py": {"timeout": 150},
    },
)
