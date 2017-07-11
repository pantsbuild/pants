# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.antlr.java.antlr_java_gen import AntlrJavaGen
from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.antlr.python.antlr_py_gen import AntlrPyGen
from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.jaxb.jaxb_gen import JaxbGen
from pants.backend.codegen.jaxb.jaxb_library import JaxbLibrary
from pants.backend.codegen.protobuf.java.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.ragel.java.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.ragel.java.ragel_gen import RagelGen
from pants.backend.codegen.thrift.java.apache_thrift_java_gen import ApacheThriftJavaGen
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.codegen.wire.java.java_wire_library import JavaWireLibrary
from pants.backend.codegen.wire.java.wire_gen import WireGen
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_antlr_library': JavaAntlrLibrary,
      'java_protobuf_library': JavaProtobufLibrary,
      'java_ragel_library': JavaRagelLibrary,
      'java_thrift_library': JavaThriftLibrary,
      'java_wire_library': JavaWireLibrary,
      'python_antlr_library': PythonAntlrLibrary,
      'python_thrift_library': PythonThriftLibrary,
      'jaxb_library': JaxbLibrary,
      }
    )


def register_goals():
  task(name='thrift-java', action=ApacheThriftJavaGen).install('gen')
  task(name='thrift-py', action=ApacheThriftPyGen).install('gen')

  # TODO(Garrett Malmquist): 'protoc' depends on a nonlocal goal (imports is in the jvm register).
  # This should be cleaned up, with protobuf stuff moved to its own backend. (See John's comment on
  # RB 592).
  task(name='protoc', action=ProtobufGen).install('gen')

  task(name='antlr-java', action=AntlrJavaGen).install('gen')
  task(name='antlr-py', action=AntlrPyGen).install('gen')
  task(name='ragel', action=RagelGen).install('gen')
  task(name='jaxb', action=JaxbGen).install('gen')
  task(name='wire', action=WireGen).install('gen')
