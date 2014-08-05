# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import signal
import sys
import tempfile

from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.base.address import BuildFileAddress, parse_spec
from pants.base.build_file import BuildFile
from pants.base.config import Config
from pants.base.target import Target
from pants.commands.command import Command
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.python_requirement import PythonRequirement


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
    parser.add_option('-i', '--interpreter', dest='interpreters', default=[], action='append',
                      help="Constrain what Python interpreters to use.  Uses Requirement "
                           "format from pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. "
                           "By default, no constraints are used.  Multiple constraints may "
                           "be added.  They will be ORed together.")
    parser.add_option('-e', '--entry_point', dest='entry_point', default=None,
                      help='The entry point for the generated PEX.')
    parser.add_option('-v', '--verbose', dest='verbose', default=False, action='store_true',
                      help='Show verbose output.')
    parser.epilog = """Interact with the chroot of the specified target."""

  def __init__(self,
               run_tracker,
               root_dir,
               parser,
               argv,
               build_file_parser,
               build_graph):
    Command.__init__(self,
                     run_tracker,
                     root_dir,
                     parser,
                     argv,
                     build_file_parser,
                     build_graph)

    self.binary = None
    self.targets = []
    self.extra_requirements = []
    self.config = Config.load()

    interpreters = self.options.interpreters or [b'']
    self.interpreter_cache = PythonInterpreterCache(self.config, logger=self.debug)
    self.interpreter_cache.setup(filters=interpreters)
    interpreters = self.interpreter_cache.select_interpreter(
        list(self.interpreter_cache.matches(interpreters)))
    if len(interpreters) != 1:
      self.error('Unable to detect suitable interpreter.')
    self.interpreter = interpreters[0]

    for req in self.options.extra_requirements:
      self.extra_requirements.append(PythonRequirement(req, use_2to3=True))

    # We parse each arg in the context of the cli usage:
    #   ./pants command (options) [spec] (build args)
    #   ./pants command (options) [spec]... -- (build args)
    # Our command token and our options are parsed out so we see args of the form:
    #   [spec] (build args)
    #   [spec]... -- (build args)
    for k in range(len(self.args)):
      arg = self.args.pop(0)
      if arg == '--':
        break

      def not_a_target(debug_msg):
        self.debug('Not a target, assuming option: %s.' % debug_msg)
        # We failed to parse the arg as a target or else it was in valid address format but did not
        # correspond to a real target.  Assume this is the 1st of the build args and terminate
        # processing args for target addresses.
        self.args.insert(0, arg)

      try:
        print(root_dir, arg)
        self.build_file_parser.inject_spec_closure_into_build_graph(arg, self.build_graph)
        spec_path, target_name = parse_spec(arg)
        build_file = BuildFile(root_dir, spec_path)
        address = BuildFileAddress(build_file, target_name)
        target = self.build_graph.get_target(address)
        if target is None:
          not_a_target(debug_msg='Unrecognized target')
          break
      except Exception as e:
        not_a_target(debug_msg=e)
        break

      if isinstance(target, PythonBinary):
        if self.binary:
          self.error('Can only process 1 binary target. Found %s and %s.' % (self.binary, target))
        else:
          self.binary = target
      self.targets.append(target)

    if not self.targets:
      self.error('No valid targets specified!')

  def debug(self, message):
    if self.options.verbose:
      print(message, file=sys.stderr)

  def execute(self):
    if self.options.pex and self.options.ipython:
      self.error('Cannot specify both --pex and --ipython!')

    if self.options.entry_point and self.options.ipython:
      self.error('Cannot specify both --entry_point and --ipython!')

    if self.options.verbose:
      print('Build operating on targets: %s' % ' '.join(str(target) for target in self.targets))


    builder = PEXBuilder(tempfile.mkdtemp(), interpreter=self.interpreter,
                         pex_info=self.binary.pexinfo if self.binary else None)

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

      for requirement in requirements:
        self.extra_requirements.append(PythonRequirement(requirement))

    executor = PythonChroot(
        targets=self.targets,
        extra_requirements=self.extra_requirements,
        builder=builder,
        platforms=self.binary.platforms if self.binary else None,
        interpreter=self.interpreter,
        conn_timeout=self.options.conn_timeout)

    executor.dump()

    if self.options.pex:
      pex_name = self.binary.name if self.binary else Target.maybe_readable_identify(self.targets)
      pex_path = os.path.join(self.root_dir, 'dist', '%s.pex' % pex_name)
      builder.build(pex_path)
      print('Wrote %s' % pex_path)
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
