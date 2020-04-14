# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python targets from Protocol Buffers (Protobufs) and gRPC.

See https://grpc.io.
"""

from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.grpcio_run import GrpcioRun
from pants.backend.codegen.grpcio.python.python_grpcio_library import (
    PythonGrpcioLibrary as PythonGrpcioLibraryV1,
)
from pants.backend.codegen.grpcio.python.targets import PythonGrpcioLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"python_grpcio_library": PythonGrpcioLibraryV1})


def register_goals():
    task(name="grpcio-prep", action=GrpcioPrep).install("gen")
    task(name="grpcio-run", action=GrpcioRun).install("gen")


def targets2():
    return [PythonGrpcioLibrary]
