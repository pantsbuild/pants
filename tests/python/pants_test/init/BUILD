# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    name="tests",
    timeout=360,
    overrides={
        ("test_options_initializer.py", "test_plugin_resolver.py"): {
            "dependencies": [
                "//BUILD_ROOT:files",
                # These tests load `pants.toml`, which references many of these plugins.
                "src/python/pants/bin:plugins",
            ],
        },
        "test_logging.py": {"dependencies": ["//BUILD_ROOT:files"]},
    },
)

python_sources()
