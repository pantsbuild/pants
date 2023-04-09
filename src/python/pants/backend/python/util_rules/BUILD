# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        "local_dists_pep660.py": dict(dependencies=["./scripts"]),
    }
)

python_tests(
    name="tests",
    overrides={
        "local_dists_test.py": {"timeout": 120},
        "pex_from_targets_test.py": {"timeout": 200},
        "pex_test.py": {"timeout": 600},
        "package_dists_test.py": {"timeout": 150},
    },
)
