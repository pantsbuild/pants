# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="test",
    overrides={
        "reversion_test.py": {"timeout": 90, "dependencies": ["3rdparty/python#pex"]},
    },
)
