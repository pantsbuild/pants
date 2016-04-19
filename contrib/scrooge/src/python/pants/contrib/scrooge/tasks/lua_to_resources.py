# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.prepare_resources import PrepareResources

from pants.contrib.scrooge.targets.lua_library import LuaLibrary


class LuaToResources(PrepareResources):
  """Adds Lua files to the classpath.

  This is useful for stacks that execute Lua inside the JVM.
  Note that this is registered as "lua-to-resources" (with dashes).
  """
  def __init__(self, *args, **kwargs):
      super(LuaToResources, self).__init__(*args, **kwargs)

  def find_all_relevant_resources_targets(self):
      def has_lua_files(target):
        return isinstance(target, LuaLibrary)
      return self.context.targets(predicate=has_lua_files)
