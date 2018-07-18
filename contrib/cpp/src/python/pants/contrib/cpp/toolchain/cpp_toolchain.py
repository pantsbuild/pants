# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import object


class CppToolchain(object):
  """Represents the cpp toolchain on the local system."""

  class Error(Exception):
    """Indicates an invalid cpp toolchain."""

  def __init__(self, compiler=None):
    """Create a cpp toolchain and cache tools for quick retrieval."""
    self._validated_tools = {}
    self._compiler = compiler

  @property
  def compiler(self):
    if 'compiler' in self._validated_tools:
      return self._validated_tools['compiler']

    _compiler = self._compiler or os.environ.get('CXX')
    if _compiler is None:
      raise self.Error('Please set the CXX environment variable or the "compiler" option.')
    return self.register_tool(name='compiler', tool=_compiler)

  def register_tool(self, tool, name=None):
    """Check tool and see if it is installed in the local cpp toolchain.

    All cpp tasks should request their tools using this method. Tools are validated
    and cached for quick lookup.

    :param string tool: Name or path of program tool, eg 'g++'
    :param string name: Logical name of tool, eg 'compiler'. If not supplied defaults to basename
                        of `tool`
    """
    name = name or os.path.basename(tool)
    if name in self._validated_tools:
      return self._validated_tools[name]

    def which(program):
      def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

      fpath, fname = os.path.split(program)
      if fpath:
        if is_exe(program):
          return program
      else:
        for path in os.environ['PATH'].split(os.pathsep):
          path = path.strip('"')
          exe_file = os.path.join(path, program)
          if is_exe(exe_file):
            return exe_file

      return None

    tool_path = which(tool)
    if tool_path is None:
      raise self.Error('Failed to locate {0}. Please install.'.format(tool))
    self._validated_tools[name] = tool_path
    return tool_path
