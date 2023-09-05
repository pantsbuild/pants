# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=["src/python/pants/backend/go/go_sources"])
python_tests(
    name="tests",
    timeout=120,
    overrides={
        "embed_integration_test.py": {"timeout": 240},
        "cgo_test.py": {"timeout": 240},
    },
)
