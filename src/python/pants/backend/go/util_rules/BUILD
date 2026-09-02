# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=["src/python/pants/backend/go/go_sources"])
python_tests(
    name="tests",
    timeout=120,
    overrides={
        # Runs once per Go coverage registration mechanism, so once per installed toolchain.
        "coverage_test.py": {"timeout": 300},
        "embed_integration_test.py": {"timeout": 240},
        "cgo_test.py": {"timeout": 240},
        "stdlib_archives_test.py": {"timeout": 240},
    },
)
