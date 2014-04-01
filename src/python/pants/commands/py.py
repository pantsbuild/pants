# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import signal
import sys
import tempfile

from twitter.common.python.pex import PEX
from twitter.common.python.pex_builder import PEXBuilder

from pants.base.address import Address
from pants.base.config import Config
from pants.base.parse_context import ParseContext
from pants.base.target import Target
from pants.commands.command import Command
from pants.python.interpreter_cache import PythonInterpreterCache
from pants.python.python_chroot import PythonChroot
from pants.targets.python_binary import PythonBinary
from pants.targets.python_requirement import PythonRequirement


class Py(Command):
  """Python chroot manipulation."""

  __command__ = 'py'

  def setup_parser(self, parser, args):
    parser.set_usage('\n'
                     '  %prog py (options) [spec] args\n')
    parser.disable_interspersed_args()
    parser.add_option('-t', '--timeout', dest='conn_timeout', type='int',
                      default=Config.load().getdefault('connection_timeout'),
                      help='Number of seconds to wait for http connections.')
    parser.add_option('--pex', dest='pex', default=False, action='store_true',
                      help='Dump a .pex of this chroot instead of attempting to execute it.')
    parser.add_option('--ipython', dest='ipython', default=False, action='store_true',
                      help='Run the target environment in an IPython interpreter.')
    parser.add_option('-r', '--req', dest='extra_requirements', default=[], action='append',
                      help='Additional Python requirements to add to this chroot.')
    parser.add_option('-i', '--interpreter', dest='interpreter', default=None,
                      help='The interpreter requirement for this chroot.')
    parser.add_option('-e', '--entry_point', dest='entry_point', default=None,
                      help='The entry point for the generated PEX.')
    parser.add_option('-v', '--verbose', dest='verbose', default=False, action='store_true',
                      help='Show verbose output.')
    parser.epilog = """Interact with the chroot of the specified target."""

  def __init__(self, run_tracker, root_dir, parser, argv):
    Command.__init__(self, run_tracker, root_dir, parser, argv)

    self.target = None
    self.extra_targets = []
    self.config = Config.load()
    self.interpreter_cache = PythonInterpreterCache(self.config, logger=self.debug)
    self.interpreter_cache.setup()
    interpreters = self.interpreter_cache.select_interpreter(
        list(self.interpreter_cache.matches([self.options.interpreter]
            if self.options.interpreter else [''])))
    if len(interpreters) != 1:
      self.error('Unable to detect suitable interpreter.')
    self.interpreter = interpreters[0]

    for req in self.options.extra_requirements:
      with ParseContext.temp():
        self.extra_targets.append(PythonRequirement(req, use_2to3=True))

    # We parse each arg in the context of the cli usage:
    #   ./pants command (options) [spec] (build args)
    #   ./pants command (options) [spec]... -- (build args)
    # Our command token and our options are parsed out so we see args of the form:
    #   [spec] (build args)
    #   [spec]... -- (build args)
    binaries = []
    for k in range(len(self.args)):
      arg = self.args.pop(0)
      if arg == '--':
        break

      def not_a_target(debug_msg):
        self.debug('Not a target, assuming option: %s.' % e)
        # We failed to parse the arg as a target or else it was in valid address format but did not
        # correspond to a real target.  Assume this is the 1st of the build args and terminate
        # processing args for target addresses.
        self.args.insert(0, arg)

      target = None
      try:
        address = Address.parse(root_dir, arg)
        target = Target.get(address)
        if target is None:
          not_a_target(debug_msg='Unrecognized target')
          break
      except Exception as e:
        not_a_target(debug_msg=e)
        break

      for resolved in filter(lambda t: t.is_concrete, target.resolve()):
        if isinstance(resolved, PythonBinary):
          binaries.append(resolved)
        else:
          self.extra_targets.append(resolved)

    if len(binaries) == 0:
      # treat as a chroot
      pass
    elif len(binaries) == 1:
      # We found a binary and are done, the rest of the args get passed to it
      self.target = binaries[0]
    else:
      self.error('Can only process 1 binary target, %s contains %d:\n\t%s' % (
        arg, len(binaries), '\n\t'.join(str(binary.address) for binary in binaries)
      ))

    if self.target is None:
      if not self.extra_targets:
        self.error('No valid target specified!')
      self.target = self.extra_targets.pop(0)

  def debug(self, message):
    if self.options.verbose:
      print(message, file=sys.stderr)

  def execute(self):
    if self.options.pex and self.options.ipython:
      self.error('Cannot specify both --pex and --ipython!')

    if self.options.entry_point and self.options.ipython:
      self.error('Cannot specify both --entry_point and --ipython!')

    if self.options.verbose:
      print('Build operating on target: %s %s' % (self.target,
        'Extra targets: %s' % ' '.join(map(str, self.extra_targets)) if self.extra_targets else ''))

    builder = PEXBuilder(tempfile.mkdtemp(), interpreter=self.interpreter,
        pex_info=self.target.pexinfo if isinstance(self.target, PythonBinary) else None)

    if self.options.entry_point:
      builder.set_entry_point(self.options.entry_point)

    if self.options.ipython:
      if not self.config.has_section('python-ipython'):
        self.error('No python-ipython sections defined in your pants.ini!')

      builder.info.entry_point = self.config.get('python-ipython', 'entry_point')
      if builder.info.entry_point is None:
        self.error('Must specify entry_point for IPython in the python-ipython section '
                   'of your pants.ini!')

      requirements = self.config.getlist('python-ipython', 'requirements', default=[])

      with ParseContext.temp():
        for requirement in requirements:
          self.extra_targets.append(PythonRequirement(requirement))

    executor = PythonChroot(
        self.target,
        self.root_dir,
        builder=builder,
        interpreter=self.interpreter,
        extra_targets=self.extra_targets,
        conn_timeout=self.options.conn_timeout)

    executor.dump()

    if self.options.pex:
      pex_name = os.path.join(self.root_dir, 'dist', '%s.pex' % self.target.name)
      builder.build(pex_name)
      print('Wrote %s' % pex_name)
      return 0
    else:
      builder.freeze()
      pex = PEX(builder.path(), interpreter=self.interpreter)
      po = pex.run(args=list(self.args), blocking=False)
      try:
        return po.wait()
      except KeyboardInterrupt:
        po.send_signal(signal.SIGINT)
        raise
