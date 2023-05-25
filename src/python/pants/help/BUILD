# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    sources=["*_test.py", "!*_integration_test.py"],
    dependencies=["//BUILD_ROOT:files"],
    overrides={
        "help_info_extracter_test.py": {
            "dependencies": [
                "//BUILD_ROOT:files",
                # Include some plugins in the test sandbox to be discovered by the help info extracter.
                "src/python/pants/backend/python/register.py",
                "pants-plugins/internal_plugins/releases/register.py",
                "testprojects/src/python/plugin:dummy-plugin-dist",
            ],
        },
    },
)

python_tests(name="integration", sources=["*_integration_test.py"], timeout=360)
