# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scrooge.targets.lua_library import LuaLibrary
from pants.contrib.scrooge.tasks.lua_to_resources import LuaToResources
from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen
from pants.contrib.scrooge.tasks.thrift_linter import ThriftLinter


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'lua_library': LuaLibrary,
    }
  )

def register_goals():
  task(name='thrift-linter', action=ThriftLinter).install()
  task(name='scrooge', action=ScroogeGen).install('gen')
  task(name='lua-to-resources', action=LuaToResources).install('resources')
