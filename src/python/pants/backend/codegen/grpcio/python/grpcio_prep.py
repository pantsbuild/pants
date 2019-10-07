# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.grpcio.python.grpcio import Grpcio
from pants.backend.codegen.grpcio.python.python_grpcio_library import PythonGrpcioLibrary
from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase


class GrpcioInstance(PythonToolInstance):
    pass


class GrpcioPrep(PythonToolPrepBase):
    tool_subsystem_cls = Grpcio
    tool_instance_cls = GrpcioInstance

    def execute(self):
        targets = self.get_targets(lambda target: isinstance(target, PythonGrpcioLibrary))
        if not targets:
            return 0

        super().execute()
