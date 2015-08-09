# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem
from pants.util.strutil import safe_shlex_split


class JVM(Subsystem):
  """A JVM invocation."""
  options_scope = 'jvm'

  @classmethod
  def register_options(cls, register):
    super(JVM, cls).register_options(register)
    # TODO(benjy): Options to specify the JVM version?
    register('--options', action='append', recursive=True, metavar='<option>...',
             help='Run with these extra JVM options.')
    register('--program-args', action='append', recursive=True, metavar='<arg>...',
             help='Run with these extra program args.')
    register('--debug', action='store_true', recursive=True,
             help='Run the JVM with remote debugging.')
    register('--debug-port', advanced=True, recursive=True, type=int, default=5005,
             help='The JVM will listen for a debugger on this port.')
    register('--debug-args', advanced=True, recursive=True, type=list_option,
             default=[
               '-Xdebug',
               '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address={debug_port}'
             ],
             help='The JVM remote-debugging arguments. {debug_port} will be replaced with '
                  'the value of the --debug-port option.')

  def get_jvm_options(self):
    """Return the options to run this JVM with.

    These are options to the JVM itself, such as -Dfoo=bar, -Xmx=1g, -XX:-UseParallelGC and so on.

    Thus named because get_options() already exists (and returns this object's Pants options).
    """
    ret = []
    for opt in self.get_options().options:
      ret.extend(safe_shlex_split(opt))

    if (self.get_options().debug or
        self.get_options().is_flagged('debug_port') or
        self.get_options().is_flagged('debug_args')):
      debug_port = self.get_options().debug_port
      ret.extend(arg.format(debug_port=debug_port) for arg in self.get_options().debug_args)
    return ret

  def get_program_args(self):
    """Get the program args to run this JVM with.

    These are the arguments passed to main() and are program-specific.
    """
    ret = []
    for arg in self.get_options().program_args:
      ret.extend(safe_shlex_split(arg))
    return ret
