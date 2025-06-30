# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        "extension_loader.py": {
            "dependencies": [
                # NB: These are explicitly loaded by default by the extension loader: see
                # the corresponding note.
                "src/python/pants/core",
                "src/python/pants/backend/project_info",
            ]
        }
    },
)

python_tests(
    name="tests",
    overrides={
        "load_backends_integration_test.py": {"timeout": 900},
        "logging_test.py": {"dependencies": ["//BUILD_ROOT:files"]},
        ("options_initializer_test.py", "plugin_resolver_test.py"): {
            "dependencies": [
                "//BUILD_ROOT:files",
                # These tests load `pants.toml`, which references many of these plugins.
                "src/python/pants/bin:plugins",
            ],
        },
        "plugin_resolver_test.py": {"timeout": 120},
    },
)
