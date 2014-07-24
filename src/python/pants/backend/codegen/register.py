# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.targets.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.targets.jaxb_library import JaxbLibrary
from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.codegen.tasks.antlr_gen import AntlrGen
from pants.backend.codegen.tasks.apache_thrift_gen import ApacheThriftGen
from pants.backend.codegen.tasks.jaxb_gen import JaxbGen
from pants.backend.codegen.tasks.protobuf_gen import ProtobufGen
from pants.backend.codegen.tasks.ragel_gen import RagelGen
from pants.backend.codegen.tasks.scrooge_gen import ScroogeGen
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal as goal


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'java_antlr_library': JavaAntlrLibrary,
      'java_protobuf_library': JavaProtobufLibrary,
      'java_ragel_library': JavaRagelLibrary,
      'java_thrift_library': JavaThriftLibrary,
      'python_antlr_library': PythonAntlrLibrary,
      'python_thrift_library': PythonThriftLibrary,
      'jaxb_library': JaxbLibrary,
      }
    )

def register_commands():
  pass


def register_goals():
  goal(name='thrift', action=ApacheThriftGen).install('gen').with_description('Generate code.')

  goal(name='scrooge', dependencies=['bootstrap'], action=ScroogeGen).install('gen')

  # TODO(Garrett Malmquist): 'protoc' depends on a nonlocal phase (imports is in the jvm register).
  # This should be cleaned up, with protobuf stuff moved to its own backend. (See John's comment on
  # RB 592).
  goal(name='protoc', dependencies=['imports'], action=ProtobufGen
  ).install('gen')

  goal(name='antlr', dependencies=['bootstrap'], action=AntlrGen
  ).install('gen')

  goal(name='ragel', action=RagelGen).install('gen')

  goal(name='jaxb', action=JaxbGen).install('gen')
