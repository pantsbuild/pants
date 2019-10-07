# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_protobuf_library import GoProtobufLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.targets.go_thrift_library import GoThriftLibrary
from pants.contrib.go.tasks.go_binary_create import GoBinaryCreate
from pants.contrib.go.tasks.go_buildgen import GoBuildgen
from pants.contrib.go.tasks.go_checkstyle import GoCheckstyle
from pants.contrib.go.tasks.go_compile import GoCompile
from pants.contrib.go.tasks.go_fetch import GoFetch
from pants.contrib.go.tasks.go_fmt import GoFmt
from pants.contrib.go.tasks.go_go import GoEnv, GoGo
from pants.contrib.go.tasks.go_protobuf_gen import GoProtobufGen
from pants.contrib.go.tasks.go_run import GoRun
from pants.contrib.go.tasks.go_test import GoTest
from pants.contrib.go.tasks.go_thrift_gen import GoThriftGen


def build_file_aliases():
  return BuildFileAliases(
    targets={
      GoBinary.alias(): TargetMacro.Factory.wrap(GoBinary.create, GoBinary),
      GoLibrary.alias(): TargetMacro.Factory.wrap(GoLibrary.create, GoLibrary),
      GoProtobufLibrary.alias(): GoProtobufLibrary,
      GoThriftLibrary.alias(): GoThriftLibrary,
      'go_remote_libraries': TargetMacro.Factory.wrap(GoRemoteLibrary.from_packages,
                                                      GoRemoteLibrary),
      'go_remote_library': TargetMacro.Factory.wrap(GoRemoteLibrary.from_package, GoRemoteLibrary),
    }
  )


def register_goals():
  task(name='go-thrift', action=GoThriftGen).install('gen')
  task(name='go-protobuf', action=GoProtobufGen).install('gen')
  task(name='go', action=GoBuildgen).install('buildgen')
  task(name='go', action=GoGo).install('go')
  task(name='go-env', action=GoEnv).install()
  task(name='go', action=GoFetch).install('resolve')
  task(name='go', action=GoCompile).install('compile')
  task(name='go', action=GoBinaryCreate).install('binary')
  task(name='go', action=GoRun).install('run')
  task(name='go', action=GoCheckstyle).install('lint')
  task(name='go', action=GoTest).install('test')
  task(name='go', action=GoFmt).install('fmt')
