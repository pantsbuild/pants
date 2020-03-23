# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget


class PythonGrpcioLibrary(PythonTarget):
    """A Python library generated from Protocol Buffer IDL files."""

    def __init__(self, sources=None, **kwargs):
        super().__init__(sources=sources, **kwargs)
