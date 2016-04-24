# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.subsystem.subsystem import Subsystem
from pants.util.strutil import safe_shlex_split


logger = logging.getLogger(__name__)


class JVM(Subsystem):
  """A JVM invocation.

  :API: public
  """
  options_scope = 'jvm'

  # Broken out here instead of being inlined in the registration stanza,
  # because various tests may need to access these.
  options_default = ['-Xmx256m']

  @classmethod
  def register_options(cls, register):
    super(JVM, cls).register_options(register)
    # TODO(benjy): Options to specify the JVM version?
    register('--options', type=list, metavar='<option>...',
             default=cls.options_default,
             help='Run with these extra JVM options.')
    register('--program-args', type=list, metavar='<arg>...',
             help='Run with these extra program args.')
    register('--debug', type=bool,
             help='Run the JVM with remote debugging.')
    register('--debug-port', advanced=True, type=int, default=5005,
             help='The JVM will listen for a debugger on this port.')
    register('--debug-args', advanced=True, type=list,
             default=[
               '-Xdebug',
               '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address={debug_port}'
             ],
             help='The JVM remote-debugging arguments. {debug_port} will be replaced with '
                  'the value of the --debug-port option.')
    register('--synthetic-classpath', advanced=True, type=bool, default=True,
             help="Use synthetic jar to work around classpath length restrictions.")

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
