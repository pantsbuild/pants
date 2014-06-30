# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.goal import Goal as goal

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.targets.jaxb_library import JaxbLibrary
from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.codegen.tasks.antlr_gen import AntlrGen
from pants.backend.codegen.tasks.apache_thrift_gen import ApacheThriftGen
from pants.backend.codegen.tasks.jaxb_gen import JaxbGen
from pants.backend.codegen.tasks.protobuf_gen import ProtobufGen
from pants.backend.codegen.tasks.scrooge_gen import ScroogeGen


def target_aliases():
  return {
    'java_antlr_library': JavaAntlrLibrary,
    'java_protobuf_library': JavaProtobufLibrary,
    'java_thrift_library': JavaThriftLibrary,
    'python_antlr_library': PythonAntlrLibrary,
    'python_thrift_library': PythonThriftLibrary,
    'jaxb_library': JaxbLibrary,
  }


def object_aliases():
  return {}


def partial_path_relative_util_aliases():
  return {}


def applicative_path_relative_util_aliases():
  return {}


def target_creation_utils():
  return {}


def register_commands():
  pass


def register_goals():
  goal(name='thrift', action=ApacheThriftGen
  ).install('gen').with_description('Generate code.')

  goal(name='scrooge', dependencies=['bootstrap'], action=ScroogeGen
  ).install('gen')

  goal(name='protoc', action=ProtobufGen
  ).install('gen')

  goal(name='antlr', dependencies=['bootstrap'], action=AntlrGen
  ).install('gen')

  goal(name='jaxb', action=JaxbGen
  ).install('gen')
