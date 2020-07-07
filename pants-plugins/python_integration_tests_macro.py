# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

def python_integration_tests(*, uses_pants_run: bool, **kwargs):
    kwargs["tags"] = [*kwargs.get("tags", []), "integration"]
    if uses_pants_run:
        kwargs["dependencies"] = [
            *kwargs.get("dependencies", []), "src/python/pants/testutil:int-test"
        ]
    if "sources" not in kwargs:
        kwargs["sources"] = ["*_integration_test.py"]
    python_tests(**kwargs)
