# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(sources=["*.sh", "pants_venv"])

resources(
    name='common_script',
    sources=["common.sh"],
)

python_tests(
    name="py_tests",
    overrides={
        "common_shell_methods_test.py": {"dependencies": [":common_script"]},
    },
)
