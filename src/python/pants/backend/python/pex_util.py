# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.interpreter import PythonInterpreter
from pex.platforms import Platform


def create_bare_interpreter(binary_path):
  """Creates an interpreter for python binary at the given path.

  The interpreter is bare in that it has no extras associated with it.

  :returns: A bare python interpreter with no extras.
  :rtype: :class:`pex.interpreter.PythonInterpreter`
  """
  # TODO(John Sirois): Replace with a more direct PythonInterpreter construction API call when
  # https://github.com/pantsbuild/pex/issues/510 is fixed.
  interpreter_with_extras = PythonInterpreter.from_binary(binary_path)
  return PythonInterpreter(binary_path, interpreter_with_extras.identity, extras=None)


def get_local_platform():
  """Returns the name of the local platform; eg: 'linux_x86_64' or 'macosx_10_8_x86_64'.

  :returns: The local platform name.
  :rtype: str
  """
  # TODO(John Sirois): Kill some or all usages when https://github.com/pantsbuild/pex/issues/511
  # is fixed.
  current_platform = Platform.current()
  return current_platform.platform
