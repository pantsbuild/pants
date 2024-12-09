# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NOTE: Sources restricted from the default for python_sources due to conflict with
#   - //:all-__init__.py-files
#   - //src/python/pants/backend/helm/lint/trivy/__init__.py:../../../../../../../all-__init__.py-files
python_sources(
    sources=[
        "register.py",
        "rules.py",
    ],
)

python_tests(
    name="tests",
)
