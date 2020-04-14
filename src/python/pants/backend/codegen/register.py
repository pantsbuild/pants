# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Enable this backend to turn on every single codegen backend within `pants.backend.codegen`."""

from pants.backend.codegen.antlr.java.antlr_java_gen import AntlrJavaGen
from pants.backend.codegen.antlr.java.java_antlr_library import (
    JavaAntlrLibrary as JavaAntlrLibraryV1,
)
from pants.backend.codegen.antlr.java.targets import JavaAntlrLibrary
from pants.backend.codegen.antlr.python.antlr_py_gen import AntlrPyGen
from pants.backend.codegen.antlr.python.python_antlr_library import (
    PythonAntlrLibrary as PythonAntlrLibraryV1,
)
from pants.backend.codegen.antlr.python.targets import PythonAntlrLibrary
from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.grpcio_run import GrpcioRun
from pants.backend.codegen.grpcio.python.python_grpcio_library import (
    PythonGrpcioLibrary as PythonGrpcioLibraryV1,
)
from pants.backend.codegen.grpcio.python.targets import PythonGrpcioLibrary
from pants.backend.codegen.jaxb.jaxb_gen import JaxbGen
from pants.backend.codegen.jaxb.jaxb_library import JaxbLibrary as JaxbLibraryV1
from pants.backend.codegen.jaxb.targets import JaxbLibrary
from pants.backend.codegen.protobuf.java.java_protobuf_library import (
    JavaProtobufLibrary as JavaProtobufLibraryV1,
)
from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.protobuf.java.targets import JavaProtobufLibrary
from pants.backend.codegen.ragel.java.java_ragel_library import (
    JavaRagelLibrary as JavaRagelLibraryV1,
)
from pants.backend.codegen.ragel.java.ragel_gen import RagelGen
from pants.backend.codegen.ragel.java.targets import JavaRagelLibrary
from pants.backend.codegen.thrift.java.apache_thrift_java_gen import ApacheThriftJavaGen
from pants.backend.codegen.thrift.java.java_thrift_library import (
    JavaThriftLibrary as JavaThriftLibraryV1,
)
from pants.backend.codegen.thrift.java.targets import JavaThriftLibrary
from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import (
    PythonThriftLibrary as PythonThriftLibraryV1,
)
from pants.backend.codegen.thrift.python.targets import PythonThriftLibrary
from pants.backend.codegen.wire.java.java_wire_library import JavaWireLibrary as JavaWireLibraryV1
from pants.backend.codegen.wire.java.targets import JavaWireLibrary
from pants.backend.codegen.wire.java.wire_gen import WireGen
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(
        targets={
            "java_antlr_library": JavaAntlrLibraryV1,
            "java_protobuf_library": JavaProtobufLibraryV1,
            "java_ragel_library": JavaRagelLibraryV1,
            "java_thrift_library": JavaThriftLibraryV1,
            "java_wire_library": JavaWireLibraryV1,
            "python_antlr_library": PythonAntlrLibraryV1,
            "python_thrift_library": PythonThriftLibraryV1,
            "python_grpcio_library": PythonGrpcioLibraryV1,
            "jaxb_library": JaxbLibraryV1,
        }
    )


def register_goals():
    task(name="thrift-java", action=ApacheThriftJavaGen).install("gen")
    task(name="thrift-py", action=ApacheThriftPyGen).install("gen")
    task(name="grpcio-prep", action=GrpcioPrep).install("gen")
    task(name="grpcio-run", action=GrpcioRun).install("gen")
    task(name="protoc", action=ProtobufGen).install("gen")
    task(name="antlr-java", action=AntlrJavaGen).install("gen")
    task(name="antlr-py", action=AntlrPyGen).install("gen")
    task(name="ragel", action=RagelGen).install("gen")
    task(name="jaxb", action=JaxbGen).install("gen")
    task(name="wire", action=WireGen).install("gen")


def targets2():
    return [
        JavaAntlrLibrary,
        PythonAntlrLibrary,
        PythonGrpcioLibrary,
        JaxbLibrary,
        JavaProtobufLibrary,
        JavaRagelLibrary,
        JavaThriftLibrary,
        PythonThriftLibrary,
        JavaWireLibrary,
    ]
