# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
python_sources(sources=["__init__.py"], dependencies=[":test_lockfiles"])

resources(
    name="test_lockfiles",
    sources=[
        "test.pex.lock",
        "test.pex.lock.metadata",
        "test.uv.lock",
        "test.uv.lock.metadata",
    ],
)
