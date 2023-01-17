# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Scripts are consumed at runtime as resources.
resources(
    sources=["**/*.py"],
)

# Also expose the scripts as python sources so they get formatted/linted/checked.
python_sources(
    name="py_sources",
    sources=["**/*.py"],
)
