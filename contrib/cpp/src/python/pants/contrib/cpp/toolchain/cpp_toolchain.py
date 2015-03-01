# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os


class CppToolchain(object):
  """
  Represents the cpp toolchain on the local system.
  """

  class Error(Exception):
    """Indicates an invalid cpp toolchain."""

  def __init__(self, compiler=None):
    """Create a cpp toolchain and cache tools for quick retrieval."""
    self._validated_tools = set()
    _compiler = compiler or os.environ.get('CXX')
    if _compiler is None:
      raise self.Error('Please set the CXX environment variable or the "compiler" option.')
    self.compiler = self.register_tool(_compiler)

  def register_tool(self, tool):
    """Check tool and see if it is installed in the local cpp toolchain.

    All cpp tasks should request their tools using this method. Tools are validated
    and cached for quick lookup.

    :param string tool: Name of tool, eg 'g++'
    """
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

    cpp_tool = which(tool)
    if cpp_tool is None:
      raise self.Error('Failed to locate {0}. Please install.'.format(tool))

    self._register_file(cpp_tool)
    return cpp_tool

  def _register_file(self, tool):
    if tool not in self._validated_tools:
      self._validated_tools.add(tool)
    return tool
