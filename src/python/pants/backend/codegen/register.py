# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Enable this backend to turn on every single codegen backend within `pants.backend.codegen`."""

from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.grpcio_run import GrpcioRun
from pants.backend.codegen.grpcio.python.python_grpcio_library import (
    PythonGrpcioLibrary as PythonGrpcioLibraryV1,
)
from pants.backend.codegen.grpcio.python.target_types import PythonGrpcioLibrary
from pants.backend.codegen.protobuf.java.java_protobuf_library import (
    JavaProtobufLibrary as JavaProtobufLibraryV1,
)
from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.protobuf.java.target_types import JavaProtobufLibrary
from pants.backend.codegen.thrift.java.apache_thrift_java_gen import ApacheThriftJavaGen
from pants.backend.codegen.thrift.java.java_thrift_library import (
    JavaThriftLibrary as JavaThriftLibraryV1,
)
from pants.backend.codegen.thrift.java.target_types import JavaThriftLibrary
from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import (
    PythonThriftLibrary as PythonThriftLibraryV1,
)
from pants.backend.codegen.thrift.python.target_types import PythonThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(
        targets={
            "java_protobuf_library": JavaProtobufLibraryV1,
            "java_thrift_library": JavaThriftLibraryV1,
            "python_thrift_library": PythonThriftLibraryV1,
            "python_grpcio_library": PythonGrpcioLibraryV1,
        }
    )


def register_goals():
    task(name="thrift-java", action=ApacheThriftJavaGen).install("gen")
    task(name="thrift-py", action=ApacheThriftPyGen).install("gen")
    task(name="grpcio-prep", action=GrpcioPrep).install("gen")
    task(name="grpcio-run", action=GrpcioRun).install("gen")
    task(name="protoc", action=ProtobufGen).install("gen")


def target_types():
    return [
        PythonGrpcioLibrary,
        JavaProtobufLibrary,
        JavaThriftLibrary,
        PythonThriftLibrary,
    ]
